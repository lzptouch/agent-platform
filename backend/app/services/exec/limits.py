"""子进程执行边界（批次 01 / WP-1）。

**诚实说明（重要）**：本模块提供的是**单机进程级边界**，**不是**容器 / 虚拟机级沙箱：

- **POSIX**：用 ``resource.setrlimit`` 限制 CPU 时间 / 地址空间 / 文件句柄 / 单文件大小；
- **Windows**：Python 标准库没有 ``resource`` → 退化为
  「工作目录 + 路径白名单 + 超时 + 输出上限」，并在返回值里如实标注 ``limit_hit``；
- **全平台共有**：**启动前**的工作目录逃逸拦截、网络出口开关、输出上限（超出即杀）。

实现取舍：

1. **不用 ``preexec_fn``**——它与线程不兼容（fork 后在子进程里跑 Python 代码可能死锁），
   而后端是多线程的（FastAPI + APScheduler）。改为在 POSIX 上用一个**引导脚本**包一层：
   ``python -c <引导> <limits-json> <真实 argv...>``，引导脚本设置 rlimit 后
   ``os.execvp`` 原地替换自身（不改变退出码与信号语义）。
2. **超时要能杀掉子孙进程**：POSIX 用 ``start_new_session=True`` 建独立进程组，
   超限时 ``killpg`` 整组；Windows 只能杀直接子进程（已在文档中标注为限制）。
3. 所有限制均可用 ``settings.exec_*`` 调整；``exec_resource_limits=false`` 即整体退回旧行为
   （回滚开关，见 ``doc/plan/01-执行边界与输入限制.md`` §五）。
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings


# --------------------------------------------------------------------------- #
# 限制项
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ExecLimits:
    """子进程资源限制（各项 <=0 表示该项不限制）。"""

    cpu_seconds: int = 60                 # CPU 时间上限（秒，POSIX 生效）
    memory_bytes: int = 1024 * 1024 * 1024  # 地址空间上限（POSIX 生效）
    open_files: int = 256                 # 文件句柄上限（POSIX 生效）
    file_size_bytes: int = 64 * 1024 * 1024  # 单文件写入上限（POSIX 生效）
    max_output_bytes: int = 64 * 1024     # stdout / stderr 各自上限
    timeout: int = 180                    # 墙钟超时（秒）

    def as_dict(self) -> dict[str, int]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "memory_bytes": self.memory_bytes,
            "open_files": self.open_files,
            "file_size_bytes": self.file_size_bytes,
        }


def limits_from_settings() -> ExecLimits:
    """从配置构造限制项。"""
    return ExecLimits(
        cpu_seconds=int(settings.exec_cpu_seconds),
        memory_bytes=int(settings.exec_memory_bytes),
        open_files=int(settings.exec_open_files),
        file_size_bytes=int(settings.exec_file_size_bytes),
        max_output_bytes=int(settings.exec_max_output_bytes),
        timeout=int(settings.exec_timeout),
    )


@dataclass
class ExecResult:
    """子进程执行结果。"""

    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    limit_hit: str = ""       # "" | "output" | "timeout" | "cpu" | "memory"
    truncated: bool = False   # 输出是否因上限被截断
    duration_ms: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0

    @property
    def ok(self) -> bool:
        return self.return_code == 0 and not self.limit_hit


# --------------------------------------------------------------------------- #
# POSIX 引导脚本（设置 rlimit 后原地替换进程）
# --------------------------------------------------------------------------- #
_POSIX_BOOTSTRAP = r"""
import json, os, resource, sys

limits = json.loads(sys.argv[1])
argv = sys.argv[2:]


def _apply(name, value):
    if not value or value <= 0:
        return
    res = getattr(resource, name, None)
    if res is None:
        return
    try:
        _soft, hard = resource.getrlimit(res)
        if hard != resource.RLIM_INFINITY and hard < value:
            value = hard
        resource.setrlimit(res, (value, value))
    except (ValueError, OSError):
        pass


_apply("RLIMIT_CPU", int(limits.get("cpu_seconds", 0)))
_apply("RLIMIT_AS", int(limits.get("memory_bytes", 0)))
_apply("RLIMIT_NOFILE", int(limits.get("open_files", 0)))
_apply("RLIMIT_FSIZE", int(limits.get("file_size_bytes", 0)))

os.execvp(argv[0], argv)
"""


# --------------------------------------------------------------------------- #
# 启动前检查：路径逃逸 / 网络出口
# --------------------------------------------------------------------------- #
#: 提取「可能含路径」的 token（带引号或裸 token）
_TOKEN_RE = re.compile(r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s"'`;|&<>()\[\]{},=]+)""")

#: 联网行为形态（用于「网络出口默认关闭」的启动前识别）
_NETWORK_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:requests|httpx|aiohttp)\s*\.\s*(?:get|post|put|delete|patch|head|request)\s*\(", re.I),
     "HTTP 客户端调用"),
    (re.compile(r"\burllib\.request\.\w+\s*\(", re.I), "urllib 联网调用"),
    (re.compile(r"\burlopen\s*\(", re.I), "urlopen 联网调用"),
    (re.compile(r"\bhttp\.client\b", re.I), "http.client 联网调用"),
    (re.compile(r"\bsocket\.socket\s*\(", re.I), "socket 联网调用"),
    (re.compile(r"^\s*import\s+(?:requests|httpx|aiohttp)\b", re.M), "联网库导入"),
    (re.compile(r"^\s*import\s+urllib\.request\b", re.M), "联网库导入"),
    (re.compile(r"^\s*from\s+urllib\s+import\s+request\b", re.M), "联网库导入"),
    (re.compile(r"(?:^|[\s;|&(])curl\s", re.I), "curl 联网命令"),
    (re.compile(r"(?:^|[\s;|&(])wget\s", re.I), "wget 联网命令"),
    (re.compile(r"(?:^|[\s;|&(])(?:nc|netcat|telnet)\s", re.I), "网络工具命令"),
    (re.compile(r"(?:^|[\s;|&(])(?:pip|pip3)\s+install\s", re.I), "pip install（需联网）"),
    (re.compile(r"(?:^|[\s;|&(])(?:npm|yarn|pnpm)\s+(?:install|i)\s", re.I), "npm install（需联网）"),
    (re.compile(r"(?:^|[\s;|&(])git\s+clone\s", re.I), "git clone（需联网）"),
)


def _is_within(path: Path, root: Path) -> bool:
    """path 是否位于 root 之内（解析符号链接后比较）。"""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except (OSError, RuntimeError):
        return False
    if resolved == root_resolved:
        return True
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def _resolve_token(root: Path, token: str) -> Path:
    """把 token 当作路径解析（相对 root，绝对路径原样）。"""
    text = token.replace("\\", "/")
    if os.name == "nt" and re.match(r"^[A-Za-z]:/", text):
        return Path(text)
    if text.startswith("/"):
        return Path(text)
    return root / text


def detect_escape(text: str, root: Path) -> str | None:
    """检测文本中的路径是否逃出 ``root``；返回逃逸片段（None = 未发现）。

    只判定**含 ``..`` 的路径 token**——绝对路径（如调用系统解释器）不因此被拒，
    绝对路径的准入由权限引擎与文件工具白名单负责。
    """
    if not text:
        return None
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).strip("\"'")
        if ".." not in token:
            continue
        if not any(sep in token for sep in ("/", "\\")) and not token.endswith(".."):
            continue
        try:
            resolved = _resolve_token(root, token)
        except (OSError, ValueError):
            continue
        if not _is_within(resolved, root):
            return token
    return None


def detect_network_usage(text: str) -> str | None:
    """检测文本中的联网形态；返回人类可读说明（None = 未发现）。"""
    if not text:
        return None
    for pattern, label in _NETWORK_PATTERNS:
        if pattern.search(text):
            return label
    return None


# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #
def _drain(stream, sink: bytearray, limit: int, overflow: threading.Event, counter: list[int]) -> None:
    """读取管道，最多保留 ``limit`` 字节；超出则置 ``overflow``。"""
    total = 0
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            total += len(chunk)
            room = limit - len(sink)
            if room > 0:
                sink.extend(chunk[:room])
            if total > limit:
                overflow.set()
                break
    except (OSError, ValueError):
        pass
    finally:
        counter.append(total)
        try:
            stream.close()
        except OSError:
            pass


def _kill(proc: subprocess.Popen) -> None:
    """杀掉子进程（POSIX 连同进程组）。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_with_limits(
    argv: list[str],
    *,
    cwd: Path,
    limits: ExecLimits,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """在资源限制下执行子进程。

    ``argv`` 是**真实**命令行（不做 shell 解析）；调用方负责决定用 ``sh -c`` 还是解释器。
    """
    timeout = timeout or limits.timeout
    started = time.monotonic()
    result = ExecResult()

    cmd: list[str] = list(argv)
    popen_kwargs: dict = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }
    if os.name == "posix":
        # 用引导脚本设置 rlimit（不用 preexec_fn：与线程不兼容）
        cmd = [sys.executable, "-c", _POSIX_BOOTSTRAP, json.dumps(limits.as_dict()), *cmd]
        # 独立进程组 → 超限时可以整组杀掉
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        return ExecResult(stderr=f"启动子进程失败: {exc}", return_code=1, duration_ms=0)

    out_buf = bytearray()
    err_buf = bytearray()
    overflow = threading.Event()
    out_count: list[int] = []
    err_count: list[int] = []
    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, out_buf, limits.max_output_bytes, overflow, out_count), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_buf, limits.max_output_bytes, overflow, err_count), daemon=True),
    ]
    for t in threads:
        t.start()

    deadline = started + timeout
    killed_by_output = False
    while True:
        if proc.poll() is not None:
            break
        if overflow.is_set():
            result.limit_hit = "output"
            killed_by_output = True
            _kill(proc)
            break
        if time.monotonic() > deadline:
            result.limit_hit = "timeout"
            _kill(proc)
            break
        time.sleep(0.02)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - 兜底
        _kill(proc)
        proc.wait()

    for t in threads:
        t.join(timeout=2)

    # 竞态兜底：子进程可能「打印完即退出」，读线程在主循环判定之后才置位溢出标记。
    # 线程 join 之后标记才是最终态 —— 此时必须补判，否则超量输出会被漏记。
    if overflow.is_set() and not result.limit_hit:
        result.limit_hit = "output"

    result.stdout = out_buf.decode("utf-8", "replace")
    result.stderr = err_buf.decode("utf-8", "replace")
    result.stdout_bytes = out_count[0] if out_count else len(out_buf)
    result.stderr_bytes = err_count[0] if err_count else len(err_buf)
    result.return_code = proc.returncode if proc.returncode is not None else -1
    result.truncated = (
        result.stdout_bytes > limits.max_output_bytes
        or result.stderr_bytes > limits.max_output_bytes
        or result.limit_hit == "output"
    )
    result.duration_ms = int((time.monotonic() - started) * 1000)

    if result.limit_hit == "timeout":
        result.stderr = (result.stderr + f"\n[执行边界] 超时（{timeout}s）已终止子进程").strip()
    elif result.limit_hit == "output":
        verb = "已终止子进程" if killed_by_output else "已截断输出"
        result.stderr = (
            result.stderr + f"\n[执行边界] 输出超过 {limits.max_output_bytes} 字节，{verb}"
        ).strip()
    return result

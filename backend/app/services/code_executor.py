"""LocalCodeExecutor —— 本地代码执行器。

对标 Anthropic 的云端代码执行沙箱：通过 ``subprocess`` 在本地执行 Python / Bash，
并把工作目录固定到 ``data/outputs``，让模型生成的文件集中落盘。

**执行边界**（批次 01 / WP-1）：

- 启动前：工作目录逃逸拦截 + 网络出口开关（默认关）；
- 运行中：CPU / 内存 / 句柄 / 单文件大小限制（POSIX）+ 墙钟超时 + 输出上限（超出即杀）；
- 每次限制命中都写审计（按 run 可还原）。

边界实现在 ``app.services.exec.limits``；``settings.exec_resource_limits=false`` 可整体退回旧行为。
"""

from __future__ import annotations

import os
import subprocess
import sys
import logging
from pathlib import Path

from app.core.config import settings
from app.services.exec.limits import (
    detect_escape,
    detect_network_usage,
    limits_from_settings,
    run_with_limits,
)


logger = logging.getLogger(__name__)


def scan_sensitive(content: str) -> dict:
    """P2-07：写前敏感信息扫描。

    策略来自 ``settings.sensitive_policy``：

    - ``allow``：只记录命中，不改内容；
    - ``encrypt``：命中片段加密（密文落盘，输出时由 ``sensitive.restore`` 还原）；
    - ``deny``：命中即拒写。

    扫描失败**不阻断写入**（宁可漏判，不可误伤）。
    """
    from app.core.config import settings
    from app.services.security import sensitive

    try:
        return sensitive.process(content, policy=settings.sensitive_policy)
    except Exception as exc:  # noqa: BLE001
        logger.warning("敏感信息扫描失败（按放行处理）: %s", exc)
        return {"action": "allow", "processed": content, "hits": []}


class LocalCodeExecutor:
    """本地代码执行器（带超时与简单危险命令拦截）。"""

    BLOCKED_COMMANDS = ["rm -rf /", "mkfs", "dd if=", ":(){", "fork bomb"]

    # matplotlib 预处理：强制 Agg 后端（防止 plt.show() 阻塞）+ 中文字体
    MPL_PREAMBLE = (
        "import matplotlib as _mpl\n"
        "_mpl.use('Agg')\n"
        "_mpl.rcParams['font.sans-serif'] = "
        "['PingFang HK', 'Heiti TC', 'Arial Unicode MS', 'STHeiti', 'SimSong']\n"
        "_mpl.rcParams['axes.unicode_minus'] = False\n"
    )

    # reportlab 预处理：注册中文字体（缺字体时静默跳过）
    REPORTLAB_PREAMBLE = (
        "from reportlab.pdfbase import pdfmetrics as _pm\n"
        "from reportlab.pdfbase.ttfonts import TTFont as _TTFont\n"
        "for _name, _path in [('ChineseFont', '/Library/Fonts/Arial Unicode.ttf'),\n"
        "                     ('ChineseFontBold', '/System/Library/Fonts/STHeiti Medium.ttc')]:\n"
        "    try:\n"
        "        _pm.registerFont(_TTFont(_name, _path))\n"
        "    except Exception:\n"
        "        pass\n"
    )

    def __init__(self, output_dir: Path | None = None, timeout: int | None = None) -> None:
        self.output_dir = Path(output_dir or settings.output_dir)
        self.timeout = timeout or settings.exec_timeout
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _limits(self):
        """当前生效的资源限制（超时以本执行器的 ``timeout`` 为准）。"""
        from dataclasses import replace

        return replace(limits_from_settings(), timeout=self.timeout)

    # ------------------------------------------------------------------ #
    # 工作目录与路径边界
    # ------------------------------------------------------------------ #
    @property
    def cwd_dir(self) -> Path:
        """命令执行的工作目录。

        **P2-18**：此前取**全局当前工作区**（可运行时切换）→ 运行中切换空间
        会影响本次 run 的写盘位置。现在**优先取本次 run 绑定的**
        ``workspace_root``（``current_run_context``，运行期锁死）；
        无 run 上下文时回落全局当前空间，再回落 ``data/outputs``。
        """
        from app.services.workspace.service import current_run_context

        ctx = current_run_context.get()
        if ctx and ctx.get("workspace_root"):
            bound = Path(str(ctx["workspace_root"]))
            if bound.exists():
                return bound

        from app.core.workspace import get_workspace_dir

        try:
            workspace = get_workspace_dir()
        except Exception:  # noqa: BLE001 - 解析失败不应阻断执行
            return self.output_dir
        if workspace.exists():
            return workspace
        return self.output_dir

    def _manifest_writable_roots(self) -> list[Path]:
        """当前工作空间 manifest 声明的 ``writable_roots``（P2-20）。"""
        try:
            from app.services.workspace.manifest import read_manifest_for
            from app.services.workspace.service import WorkspaceService, current_run_context

            ctx = current_run_context.get()
            workspace_id = (ctx or {}).get("workspace_id")
            if not workspace_id:
                current = WorkspaceService.instance().current()
                workspace_id = current.id if current else None
            if not workspace_id:
                return []
            # P2-20 修复：按工作空间**真实 root_path** 读（此前读不到写入的文件）
            manifest = read_manifest_for(str(workspace_id))
            out: list[Path] = []
            for raw in manifest.get("writable_roots") or []:
                try:
                    out.append(Path(str(raw)).expanduser())
                except Exception:  # noqa: BLE001
                    continue
            return out
        except Exception:  # noqa: BLE001 - manifest 不可读不应阻断执行
            return []

    @property
    def allowed_roots(self) -> list[Path]:
        """文件工具允许访问的根目录（**写操作全形态生效**）。

        **P1-09**：此前**仅桌面模式生效**——Web 形态返回 ``[]`` →
        ``_check_allowed`` 直接放行 → 模型给出的**任意绝对路径**都可写入，
        绕过工作区约束。

        现在默认两个根：

        1. 当前工作区（``cwd_dir``）
        2. 平台产出目录（``output_dir``）—— 把产物写进 ``data/outputs``
           是合法且常见的，不应被拦。
        """
        roots = [self.cwd_dir]
        # P2-20：manifest 的 ``writable_roots`` 是**追加的可写根**——
        # 此前 manifest 五字段无读取方，「改 manifest 即生效」不成立。
        for extra in self._manifest_writable_roots():
            if extra not in roots:
                roots.append(extra)
        out = self.output_dir
        if out not in roots:
            roots.append(out)
        return roots

    def _check_allowed(self, path: Path, *, for_write: bool = False) -> str | None:
        """校验路径是否在允许范围内；返回错误说明（None 表示放行）。

        **P1-09** 的边界口径：

        - **写**（``write_file``）：**全形态**都受工作区边界约束；
        - **读**（``read_file`` / ``list_directory``）：
          桌面态保持与写同一条边界（不削弱既有能力）；
          Web 形态**不设硬边界**——读工作区外的源码/配置/资料库 PDF 是
          合法且常见的，其边界由权限引擎（``file`` scope）负责。

        空 roots = 不限制。
        """
        from app.core.config import settings as _settings

        if for_write or _settings.desktop_mode:
            roots = self.allowed_roots
        else:
            roots = []
        if not roots:
            return None
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            return f"无法解析路径: {path}"
        for root in roots:
            try:
                resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            return None
        return f"路径超出允许的工作区范围: {path}"

    # ------------------------------------------------------------------ #
    # 安全检查
    # ------------------------------------------------------------------ #
    def _blocked(self, text: str) -> str | None:
        for blocked in self.BLOCKED_COMMANDS:
            if blocked in text:
                return f"安全限制：禁止执行包含 '{blocked}' 的内容"
        return None

    # ------------------------------------------------------------------ #
    # 执行边界（批次 01 / WP-1）
    # ------------------------------------------------------------------ #
    def _preflight(self, tool: str, text: str) -> str | None:
        """**启动前**的边界检查；返回拒绝原因（None = 放行）。

        顺序：路径逃逸 → 网络出口。两项都在子进程启动**之前**判定，
        不依赖运行期拦截（被拒时不会有任何进程被创建）。
        """
        if not settings.exec_resource_limits:
            return None
        if settings.exec_workspace_escape_check:
            escaped = detect_escape(text, self.cwd_dir)
            if escaped:
                return (
                    f"执行边界：路径 {escaped!r} 逃出工作目录 {self.cwd_dir}，已在启动前拒绝"
                )
        if not settings.exec_network_enabled:
            network = detect_network_usage(text)
            if network:
                return f"执行边界：检测到联网行为（{network}），网络出口默认关闭，已在启动前拒绝"
        return None

    def _audit(self, tool: str, decision: str, reason: str, target: str) -> None:
        """写一条边界审计（失败不阻断主流程）。"""
        try:
            from app.services.security.audit import record
            from app.services.workspace.service import current_run_context

            ctx = current_run_context.get()
            record(
                run_id=(ctx or {}).get("run_id"),
                tool=tool,
                decision=decision,
                reason=reason,
                target=target[:200],
            )
        except Exception as exc:  # noqa: BLE001 - 审计失败不阻断
            logger.debug("执行边界审计写入失败: %s", exc)

    @staticmethod
    def _shell_argv(command: str) -> list[str]:
        """构造 shell 命令行（等价于原来的 ``shell=True``）。"""
        if os.name == "nt":
            return [os.environ.get("COMSPEC", "cmd.exe"), "/c", command]
        return ["/bin/sh", "-c", command]

    # ------------------------------------------------------------------ #
    # 执行
    # ------------------------------------------------------------------ #
    def execute_python(self, code: str) -> dict:
        """执行 Python 代码，返回 stdout / stderr / return_code。"""
        blocked = self._blocked(code)
        if blocked:
            return {"stdout": "", "stderr": blocked, "return_code": 1}

        denied = self._preflight("execute_python", code)
        if denied:
            self._audit("execute_python", "deny", denied, code)
            return {"stdout": "", "stderr": denied, "return_code": 1, "limit_hit": "preflight"}

        if "matplotlib" in code or "plt" in code:
            code = self.MPL_PREAMBLE + code
            code = code.replace("plt.show()", "# plt.show() removed - non-interactive")

        if "reportlab" in code:
            code = self.REPORTLAB_PREAMBLE + code

        if not settings.exec_resource_limits:
            try:
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=str(self.cwd_dir),
                )
                return {
                    "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
                    "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                    "return_code": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"stdout": "", "stderr": f"执行超时（{self.timeout}秒）", "return_code": 1}
            except Exception as exc:  # pragma: no cover - 兜底
                return {"stdout": "", "stderr": str(exc), "return_code": 1}

        result = run_with_limits(
            [sys.executable, "-c", code],
            cwd=self.cwd_dir,
            limits=self._limits(),
        )
        if result.limit_hit:
            self._audit("execute_python", "limit", f"命中 {result.limit_hit} 限制", code)
        return {
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "return_code": result.return_code,
            "limit_hit": result.limit_hit,
            "truncated": result.truncated,
        }

    def execute_bash(self, command: str) -> dict:
        """执行 Bash 命令，工作目录为 output_dir。"""
        blocked = self._blocked(command)
        if blocked:
            return {"stdout": "", "stderr": blocked, "return_code": 1}

        denied = self._preflight("execute_bash", command)
        if denied:
            self._audit("execute_bash", "deny", denied, command)
            return {"stdout": "", "stderr": denied, "return_code": 1, "limit_hit": "preflight"}

        if not settings.exec_resource_limits:
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=str(self.cwd_dir),
                )
                return {
                    "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
                    "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                    "return_code": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"stdout": "", "stderr": f"执行超时（{self.timeout}秒）", "return_code": 1}
            except Exception as exc:  # pragma: no cover - 兜底
                return {"stdout": "", "stderr": str(exc), "return_code": 1}

        result = run_with_limits(
            self._shell_argv(command),
            cwd=self.cwd_dir,
            limits=self._limits(),
        )
        if result.limit_hit:
            self._audit("execute_bash", "limit", f"命中 {result.limit_hit} 限制", command)
        return {
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "return_code": result.return_code,
            "limit_hit": result.limit_hit,
            "truncated": result.truncated,
        }

    # ------------------------------------------------------------------ #
    # 文件操作
    # ------------------------------------------------------------------ #
    def read_file(self, file_path: str) -> dict:
        try:
            path = self._resolve(file_path)
            denied = self._check_allowed(path)
            if denied:
                return {"content": "", "error": denied}
            if not path.exists():
                return {"content": "", "error": f"文件不存在: {file_path}"}
            content = path.read_text(encoding="utf-8")
            if len(content) > 20000:
                content = content[:20000] + "\n\n... [文件过大，已截断] ..."
            return {"content": content, "error": ""}
        except Exception as exc:
            return {"content": "", "error": str(exc)}

    def write_file(self, file_path: str, content: str) -> dict:
        try:
            path = self._resolve(file_path)
            denied = self._check_allowed(path, for_write=True)
            if denied:
                return {"success": False, "path": file_path, "error": denied}
            # S3：有 run 上下文时做写前快照 + 变更落账（快照失败不阻断写入）
            existed = path.exists()
            snapshot = None
            ctx = None
            try:
                from app.services.workspace.service import current_run_context
                from app.services.workspace.snapshots import record_change, snapshot_before_write

                ctx = current_run_context.get()
                if ctx:
                    snapshot = snapshot_before_write(
                        ctx["run_id"], Path(ctx["workspace_root"]), path, "write_file"
                    )
            except Exception:  # noqa: BLE001 —— 快照失败不阻断写入
                ctx = None
            # P2-07：写前扫描敏感信息（按 settings.sensitive_policy 处置）
            scan = scan_sensitive(content)
            if scan["action"] == "deny":
                return {
                    "success": False,
                    "path": file_path,
                    "error": f"内容含敏感信息，已按策略拒绝写入：{scan['hits']}",
                }
            content = scan["processed"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            if ctx:
                try:
                    from app.services.workspace.snapshots import record_change

                    record_change(
                        ctx["run_id"], ctx["workspace_id"], Path(ctx["workspace_root"]),
                        path, "modify" if existed else "create", "write_file", snapshot,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("变更落账失败: %s", exc)
            return {"success": True, "path": str(path), "error": ""}
        except Exception as exc:
            return {"success": False, "path": file_path, "error": str(exc)}

    def list_directory(self, dir_path: str) -> dict:
        try:
            path = self._resolve(dir_path)
            denied = self._check_allowed(path)
            if denied:
                return {"entries": [], "error": denied}
            if not path.exists():
                return {"entries": [], "error": f"目录不存在: {dir_path}"}
            entries = [
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
                for item in sorted(path.iterdir())
            ]
            return {"entries": entries, "error": ""}
        except Exception as exc:
            return {"entries": [], "error": str(exc)}

    def _resolve(self, raw: str) -> Path:
        """解析文件路径：相对路径相对工作目录，绝对路径原样。"""
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.cwd_dir / path
        return path

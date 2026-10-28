"""安全策略集与请求归一化（S2 / WP-2.2 / WP-2.4）。

全部是**纯函数**，不碰 DB、不碰全局可变状态 —— 便于契约测试冻结语义。

归一化三种请求：
- 文件路径：``~`` 展开 → 绝对化 → 符号链接 resolve → ``..`` 归一 → Windows 大小写/分隔符归一；
- 命令：去引号/重定向 → 拆 ``;`` / ``&&`` / ``||`` 逐段 → 取首 token 与前两 token 作前缀键；
- 网络：URL → host:port，判本地地址。
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from urllib.parse import urlparse

# --------------------------------------------------------------------------- #
# 文件路径归一化
# --------------------------------------------------------------------------- #
def normalize_path(raw: str | Path, *, cwd: Path | None = None) -> str:
    """把任意形态的路径归一到可直接比对的绝对路径。

    覆盖：``~`` 展开、相对路径（以 cwd 为基）、``..`` 穿越归一、符号链接解析、
    Windows 分隔符与大小写归一。
    """
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        p = (cwd or Path.cwd()) / p
    # resolve() 会解析符号链接并归一 ..；文件不存在时也能工作（strict=False）
    resolved = str(p.resolve())
    return os.path.normcase(resolved)


def path_matches_pattern(path: str, pattern: str) -> bool:
    """glob 匹配（**支持 `**` 与 `*`**）。

    ``pattern`` 里允许 ``~`` 开头；匹配前同样做归一化。
    """
    pat = normalize_path(pattern) if pattern.startswith("~") else pattern
    p = path
    # 统一分隔符便于跨平台比对
    pat_norm = pat.replace("\\", "/")
    p_norm = p.replace("\\", "/")
    regex = re.escape(pat_norm).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, p_norm) is not None


def is_local_address(host: str) -> bool:
    """是否本地地址（127.0.0.1 / localhost / ::1 / 空）。"""
    h = (host or "").strip().lower()
    return h in {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""} or h.endswith(".localhost")


def normalize_network(url: str) -> dict:
    """URL → ``{host, port, is_local}``。"""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or ""
    return {
        "host": host,
        "port": parsed.port,
        "is_local": is_local_address(host),
    }


# --------------------------------------------------------------------------- #
# 命令归一化（串联命令逐段判定）
# --------------------------------------------------------------------------- #
_COMMAND_SEPARATORS = re.compile(r"(?:;|&&|\|\|)")


def split_command_segments(command: str) -> list[str]:
    """把串联命令拆成逐段（``a && b; c`` → ``[a, b, c]``）。"""
    parts = _COMMAND_SEPARATORS.split(command)
    return [p.strip() for p in parts if p.strip()]


def normalize_command(segment: str) -> dict:
    """单段命令 → ``{tokens, first, prefix2}``。

    - 剥离引号与重定向（``> file`` / ``2>&1`` / ``< file``）；
    - ``first`` = 首 token；``prefix2`` = 前两 token（如 ``git reset``）。
    """
    # 去重定向
    seg = re.sub(r"[0-9]?>>?\s*\S+|[0-9]?<\s*\S+", "", segment).strip()
    try:
        tokens = shlex.split(seg, posix=True)
    except ValueError:
        tokens = seg.split()
    if not tokens:
        return {"tokens": [], "first": "", "prefix2": ""}
    return {
        "tokens": tokens,
        "first": tokens[0],
        "prefix2": " ".join(tokens[:2]) if len(tokens) >= 2 else tokens[0],
    }


# --------------------------------------------------------------------------- #
# 策略集（内置；规则表可覆盖）
# --------------------------------------------------------------------------- #
#: 递归守卫目录（批量删除这些目录需要审批）
RECURSION_GUARD = ("~", "~/Desktop", "~/Downloads", "~/Documents")

#: Python 代码危险调用标记
PYTHON_DANGEROUS_PATTERNS = (
    "os.remove",
    "os.unlink",
    "shutil.rmtree",
    "shutil.rmtree(",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "os.system",
    "eval(",
    "exec(",
)


def python_has_dangerous_calls(code: str) -> list[str]:
    """扫描 Python 代码中的危险调用，返回命中的标记列表。"""
    return [p for p in PYTHON_DANGEROUS_PATTERNS if p in code]


def command_is_dangerous_prefix(prefix: str, forbidden: list[tuple[str, str]]) -> tuple[str, str] | None:
    """判定命令前缀是否命中危险清单。

    ``forbidden`` 元素是 ``(pattern, decision)``；按**最长前缀**匹配。
    返回命中的 ``(pattern, decision)``，未命中返回 ``None``。
    """
    best: tuple[str, str] | None = None
    for pattern, decision in forbidden:
        if prefix.startswith(pattern) and (best is None or len(pattern) > len(best[0])):
            best = (pattern, decision)
    return best

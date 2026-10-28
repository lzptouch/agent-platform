"""工作区（Agent 执行 cwd / 产物目录）解析。

桌面端允许用户随时切换工作区，且要求**立即生效**（不重启后端）。
因此工作区不能是构造时固定的属性，而是进程内的可变状态：

- 默认值来自 ``settings.default_workspace_dir``（桌面态 = ``UserData/workspace``）；
- ``set_workspace_dir`` 会覆盖默认值，直到进程退出；
- Web 形态下同样可用（默认回落 ``data/outputs``），行为与改造前一致。
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings

_override: Path | None = None


def get_workspace_dir() -> Path:
    """当前工作区目录。"""
    if _override is not None:
        return _override
    return settings.default_workspace_dir


def set_workspace_dir(path: Path | str) -> Path:
    """切换工作区，立即生效。返回落定后的绝对路径。"""
    global _override
    _override = Path(path).expanduser()
    return _override


def reset_workspace_dir() -> None:
    """清除覆盖，回到默认工作区（测试用）。"""
    global _override
    _override = None


def is_in_workspace(path: Path | str) -> bool:
    """判断路径是否位于工作区内（用于信任分层判定）。"""
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    try:
        root = get_workspace_dir().resolve()
    except (OSError, RuntimeError):
        return False
    if target == root:
        return True
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True

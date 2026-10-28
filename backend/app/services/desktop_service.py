"""DesktopService —— 桌面端配置、工作区与运行态快照。

职责边界：

- **配置**（``desktop_preferences`` 单行）：工作区、默认模式、通知开关、远端地址；
- **工作区**：用户显式选择的目录，即 Agent 的执行 cwd 与产物落地目录，
  切换后**立即生效**（不重启后端）；
- **运行态**：给设置页与状态页提供快照（版本、数据目录、组件、调度器角色）。
"""
from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path

from sqlalchemy import select

from app.core import workspace as workspace_module
from app.core.config import settings
from app.db.base import db_session
from app.db.models import DesktopPreferenceRow, utc_now

logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES = {
    "workspace_dir": "",
    "default_mode": "chat",
    "danger_tools": 0,
    "notify_on_run": 1,
    "notify_channel": "system",
    "remote_mode": 0,
    "remote_base": "",
}

# 统一取值集合（S1）：与 schemas/agent.py、schemas/session.py 一致
VALID_MODES = ("chat", "plan", "work")
VALID_NOTIFY_CHANNELS = ("system", "toast", "off")


class DesktopService:
    """桌面端配置与运行态。"""

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def get_preferences(self) -> dict:
        with db_session() as db:
            row = db.get(DesktopPreferenceRow, 1)
            if row is None:
                row = DesktopPreferenceRow(id=1)
                db.add(row)
                db.flush()
            data = self._row_to_dict(row)
        if not data.get("workspace_dir"):
            data["workspace_dir"] = str(workspace_module.get_workspace_dir())
        return data

    def update_preferences(self, payload: dict) -> dict:
        """部分更新；未出现的字段保持不变。"""
        with db_session() as db:
            row = db.get(DesktopPreferenceRow, 1)
            if row is None:
                row = DesktopPreferenceRow(id=1)
                db.add(row)
                db.flush()

            if "default_mode" in payload:
                mode = str(payload["default_mode"])
                if mode not in VALID_MODES:
                    raise ValueError(f"未知的默认模式: {mode}")
                row.default_mode = mode
            if "notify_on_run" in payload:
                row.notify_on_run = 1 if payload["notify_on_run"] else 0
            if "notify_channel" in payload:
                channel = str(payload["notify_channel"])
                if channel not in VALID_NOTIFY_CHANNELS:
                    raise ValueError(f"未知的通知通道: {channel}")
                row.notify_channel = channel
            if "remote_mode" in payload:
                row.remote_mode = 1 if payload["remote_mode"] else 0
            if "remote_base" in payload:
                row.remote_base = str(payload["remote_base"]).strip()
            if "workspace_dir" in payload:
                # 工作区走独立端点（有存在性与可写校验），这里只做透传
                row.workspace_dir = str(payload["workspace_dir"])

            row.updated_at = utc_now()
            db.flush()
            return self._row_to_dict(row)

    # ------------------------------------------------------------------ #
    # 工作区
    # ------------------------------------------------------------------ #
    def get_workspace(self) -> dict:
        path = workspace_module.get_workspace_dir()
        return {
            "workspace_dir": str(path),
            "exists": path.exists(),
            "writable": self._is_writable(path),
        }

    def set_workspace(self, raw_path: str) -> dict:
        """切换工作区（立即生效）。目录不存在或不可写时抛 ``ValueError``。"""
        candidate = Path(str(raw_path)).expanduser()
        if not candidate.is_absolute():
            raise ValueError("工作区必须是绝对路径")
        candidate = candidate.resolve()
        if not candidate.exists():
            raise ValueError(f"目录不存在: {candidate}")
        if not candidate.is_dir():
            raise ValueError(f"不是目录: {candidate}")
        if not self._is_writable(candidate):
            raise ValueError(f"目录不可写: {candidate}")

        previous = str(workspace_module.get_workspace_dir())
        workspace_module.set_workspace_dir(candidate)
        with db_session() as db:
            row = db.get(DesktopPreferenceRow, 1)
            if row is None:
                row = DesktopPreferenceRow(id=1)
                db.add(row)
            row.workspace_dir = str(candidate)
            row.updated_at = utc_now()
        return {
            "ok": True,
            "workspace_dir": str(candidate),
            "writable": True,
            "previous": previous,
            "effective": "immediate",
        }

    # ------------------------------------------------------------------ #
    # 运行态
    # ------------------------------------------------------------------ #
    def status(self, scheduler_health: dict | None = None) -> dict:
        components = self.components()
        return {
            "mode": "remote" if self.get_preferences().get("remote_mode") else "local",
            "app_version": settings.app_version,
            "backend_version": settings.app_version,
            "protocol": settings.desktop_protocol,
            "started_at": utc_now(),
            "data_dir": str(settings.user_data_dir),
            "workspace_dir": str(workspace_module.get_workspace_dir()),
            "runtime": {
                "python": platform.python_version(),
                "executable": sys.executable,
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            "components": components,
            "scheduler": scheduler_health or {},
            "security": {
                "auth_required": settings.desktop_mode,
                "cors_origins": settings.cors_origin_list,
                "permission_level": None,
            },
        }

    def components(self) -> dict:
        """已安装组件状态（当前只有 Playwright 浏览器）。"""
        browsers_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        installed = False
        size = 0
        path = browsers_root
        if browsers_root:
            root = Path(browsers_root)
            installed = root.exists() and any(root.iterdir())
            if installed:
                for item in root.rglob("*"):
                    if item.is_file():
                        size += item.stat().st_size
        return {
            "playwright_chromium": {
                "installed": installed,
                "path": path,
                "size_bytes": size,
            }
        }

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_writable(path: Path) -> bool:
        try:
            return path.exists() and os.access(path, os.W_OK)
        except OSError:
            return False

    @staticmethod
    def _row_to_dict(row: DesktopPreferenceRow) -> dict:
        return {
            "workspace_dir": row.workspace_dir or "",
            "default_mode": row.default_mode,
            "danger_tools": bool(row.danger_tools),
            "notify_on_run": bool(row.notify_on_run),
            "notify_channel": row.notify_channel,
            "remote_mode": bool(row.remote_mode),
            "remote_base": row.remote_base or "",
            "updated_at": row.updated_at,
        }

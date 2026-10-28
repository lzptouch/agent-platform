"""工作空间注册表与当前选择（S3 / WP-3.1 / WP-3.2）。

把"工作目录"升格为一等资源：创建 / 列表 / 切换 / 归档；run 绑定独立
``workspace_id``（运行期不随全局切换变化）。
"""
from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.workspace import get_workspace_dir, set_workspace_dir
from app.db.base import db_session
from app.db.models import WorkspaceRow, utc_now
from app.services.workspace import manifest as mf

logger = logging.getLogger(__name__)

#: 当前 run 的工作空间上下文（由 run 执行器在进入时设置）
current_run_context: ContextVar[dict | None] = ContextVar("run_workspace_ctx", default=None)

_ctx_lock = threading.Lock()


def _new_workspace_id() -> str:
    # 时间戳分辨率在快速连续创建时不够（Windows 上尤其明显）→ 用 uuid 保证唯一
    import uuid

    stamp = datetime.now().strftime("%Y%m%d")
    return f"wb-{stamp}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    root_path: str
    status: str
    created_at: str


class WorkspaceService:
    """工作空间 CRUD 与当前选择（进程内单例）。"""

    _instance: "WorkspaceService | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._current_id: str | None = None

    @classmethod
    def instance(cls) -> "WorkspaceService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_for_test(cls) -> None:
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(self, name: str, root_path: str | None = None) -> Workspace:
        """创建工作空间。

        - 指定 ``root_path``：以该目录为工作空间根（复用用户目录），在其下建
          ``.agent/`` 与 ``artifacts/``；
        - 未指定：在 ``settings.data_dir`` 下自动创建 ``wb-{日期}-{短ID}/`` 独立目录。
        """
        ws_id = _new_workspace_id()
        if root_path:
            ws_root = Path(root_path).expanduser()
            container = ws_root.parent          # 布局目录建在根的上一级
        else:
            container = Path(settings.data_dir)
            ws_root = container / ws_id
        mf.ensure_layout(container, ws_id if not root_path else ws_root.name)
        mf.write_manifest(container, ws_id if not root_path else ws_root.name, {})

        with db_session() as db:
            row = WorkspaceRow(
                id=ws_id,
                name=name or ws_id,
                root_path=str(ws_root),
                status="active",
                manifest_json="{}",
            )
            db.add(row)
            db.flush()
        logger.info("创建工作空间: %s -> %s", ws_id, ws_root)
        return Workspace(ws_id, name or ws_id, str(ws_root), "active", utc_now())

    def list(self, include_archived: bool = False) -> list[Workspace]:
        with db_session() as db:
            stmt = select(WorkspaceRow).order_by(WorkspaceRow.updated_at.desc())
            if not include_archived:
                stmt = stmt.where(WorkspaceRow.status == "active")
            return [
                Workspace(r.id, r.name, r.root_path, r.status, r.created_at)
                for r in db.scalars(stmt).all()
            ]

    def get(self, workspace_id: str) -> Workspace | None:
        with db_session() as db:
            row = db.get(WorkspaceRow, workspace_id)
            if not row:
                return None
            return Workspace(row.id, row.name, row.root_path, row.status, row.created_at)

    def switch(self, workspace_id: str) -> Workspace:
        """切换当前工作空间（立即生效；**不影响**已绑定 run 的工作空间）。"""
        ws = self.get(workspace_id)
        if ws is None:
            raise ValueError(f"工作空间不存在: {workspace_id}")
        if ws.status != "active":
            raise ValueError(f"工作空间已归档: {workspace_id}")
        self._current_id = workspace_id
        set_workspace_dir(ws.root_path)
        return ws

    def archive(self, workspace_id: str) -> bool:
        """归档（**不删磁盘文件**）。"""
        with db_session() as db:
            row = db.get(WorkspaceRow, workspace_id)
            if not row:
                return False
            row.status = "archived"
            row.updated_at = utc_now()
        return True

    def current(self) -> Workspace | None:
        if self._current_id is None:
            return None
        return self.get(self._current_id)

    # ------------------------------------------------------------------ #
    # run 绑定（WP-3.2）
    # ------------------------------------------------------------------ #
    def bind_for_run(self, workspace_id: str | None = None, name: str = "") -> tuple[str, Path]:
        """为一次 run 解析工作空间：未指定则自动创建独立空间。

        返回 ``(workspace_id, workspace_root)``。结果写入 run 的 meta_json，
        运行期锁死（不随全局切换变化）。
        """
        if workspace_id:
            ws = self.get(workspace_id)
            if ws is None:
                raise ValueError(f"工作空间不存在: {workspace_id}")
            return ws.id, Path(ws.root_path)
        ws = self.create(name=name or "auto")
        return ws.id, Path(ws.root_path)


INTERNAL_DIR_NAME = mf.INTERNAL_DIR

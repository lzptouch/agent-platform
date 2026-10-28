"""工作空间与运行产物/变更 API（S3）。

- 工作空间 CRUD + 切换 + 归档；
- 运行产物（交付物）/ 变更 / diff / 回退。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

from app.core.errors import AppError, ErrorCode
from app.services.workspace import artifacts as art
from app.services.workspace import changes as chg
from app.services.workspace.service import WorkspaceService

router = APIRouter(tags=["workspace"])


def _ws_root(workspace_id: str | None) -> Path:
    svc = WorkspaceService.instance()
    if workspace_id:
        ws = svc.get(workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail=f"工作空间不存在: {workspace_id}")
        return Path(ws.root_path)
    cur = svc.current()
    if cur is not None:
        return Path(cur.root_path)
    from app.core.workspace import get_workspace_dir

    return get_workspace_dir()


# --------------------------------------------------------------------------- #
# 工作空间
# --------------------------------------------------------------------------- #
@router.get("/workspaces", summary="工作空间列表")
def list_workspaces(include_archived: bool = Query(default=False)) -> dict:
    svc = WorkspaceService.instance()
    return {
        "items": [
            {"id": w.id, "name": w.name, "root_path": w.root_path, "status": w.status, "created_at": w.created_at}
            for w in svc.list(include_archived=include_archived)
        ],
        "current": (svc.current().id if svc.current() else None),
    }


@router.post("/workspaces", status_code=201, summary="创建工作空间")
def create_workspace(payload: dict = Body(default_factory=dict)) -> dict:
    name = str(payload.get("name", "")).strip()
    root_path = payload.get("root_path")
    try:
        ws = WorkspaceService.instance().create(name=name, root_path=root_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": ws.id, "name": ws.name, "root_path": ws.root_path, "status": ws.status}


@router.post("/workspaces/{workspace_id}/switch", summary="切换当前工作空间")
def switch_workspace(workspace_id: str) -> dict:
    try:
        ws = WorkspaceService.instance().switch(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "current": ws.id, "root_path": ws.root_path}


@router.post("/workspaces/{workspace_id}/archive", summary="归档工作空间（不删磁盘文件）")
def archive_workspace(workspace_id: str) -> dict:
    ok = WorkspaceService.instance().archive(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"工作空间不存在: {workspace_id}")
    return {"ok": True, "archived": workspace_id}


# --------------------------------------------------------------------------- #
# 变更与产物
# --------------------------------------------------------------------------- #
@router.get("/runs/{run_id}/changes", summary="一次 run 的变更列表")
def run_changes(run_id: str) -> dict:
    return {"items": chg.list_changes(run_id)}


@router.get("/runs/{run_id}/artifacts", summary="一次 run 的交付物（不含中间文件）")
def run_artifacts(run_id: str) -> dict:
    return {"items": art.list_artifacts(run_id)}


@router.get("/changes/{change_id}/diff", summary="一次变更的 diff")
def change_diff(change_id: int, workspace_id: str | None = Query(default=None)) -> dict:
    try:
        return chg.compute_diff(change_id, _ws_root(workspace_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/changes/{change_id}/revert", summary="回退一次变更（从快照恢复）")
def change_revert(change_id: int, payload: dict = Body(default_factory=dict)) -> dict:
    # 回退走权限判定（写操作）
    from app.services.security.permissions import PermissionRequest, PermissionService

    with_workspace = payload.get("workspace_id")
    root = _ws_root(with_workspace)
    with_permission = PermissionService.instance()
    check = with_permission.enforce(
        PermissionRequest(tool="write_file", path=str(root)),
        run_id=None,
    )
    if not check.allowed:
        raise AppError(ErrorCode.PERMISSION, f"回退被权限策略拒绝（{check.reason}）", status_code=403)
    try:
        return chg.revert(change_id, root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/artifacts/{artifact_id}/save-as", summary="产物另存到指定位置")
def artifact_save_as(run_id: str, artifact_id: int, payload: dict = Body(default_factory=dict)) -> dict:
    dest = payload.get("dest")
    if not dest:
        raise HTTPException(status_code=422, detail="缺少 dest")
    try:
        return art.save_as(artifact_id, _ws_root(payload.get("workspace_id")), dest)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

"""工作空间与运行产物/变更 API（S3）。

- 工作空间 CRUD + 切换 + 归档；
- 运行产物（交付物）/ 变更 / diff / 回退。
"""
from __future__ import annotations

import logging

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

from app.core.errors import AppError, ErrorCode
from app.services.workspace import artifacts as art
from app.services.workspace import changes as chg
from app.services.workspace.service import WorkspaceService

logger = logging.getLogger(__name__)

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


@router.get("/workspaces/{workspace_id}/manifest", summary="读取工作空间 manifest")
def get_workspace_manifest(workspace_id: str) -> dict:
    """P2-20：manifest 五字段（``writable_roots`` / ``default_policy`` / ``model`` /
    ``skills`` / ``extensions``）此前**无端点、无读取方** → 「变更即生效」不成立。"""
    # P2-20 修复：按工作空间**真实 root_path** 读（此前用当前工作区目录 → 读不到）
    from app.services.workspace.manifest import read_manifest_for

    return {"workspace_id": workspace_id, "manifest": read_manifest_for(workspace_id)}


@router.put("/workspaces/{workspace_id}/manifest", summary="更新工作空间 manifest")
def put_workspace_manifest(workspace_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    """更新 manifest；``writable_roots`` 立即影响**下一次写文件**的权限判定。"""
    # P2-20 修复：按工作空间**真实 root_path** 写
    from app.services.workspace.manifest import write_manifest_for

    try:
        manifest = write_manifest_for(workspace_id, dict(payload or {}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"workspace_id": workspace_id, "manifest": manifest}


@router.post("/workspaces/{workspace_id}/switch", summary="切换当前工作空间")
def switch_workspace(workspace_id: str) -> dict:
    try:
        ws = WorkspaceService.instance().switch(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # F-ENG-04：与桌面端点**一致**地广播事件——
    # 此前只有 `/desktop/switch` 会 publish，Web 形态切了工作空间，
    # 桌面壳的渲染进程收不到通知（两种形态行为不一致）。
    try:
        from app.desktop.events import bus

        bus.publish("workspace_changed", workspace_dir=ws.root_path)
    except Exception:  # noqa: BLE001 - 广播失败不影响切换本身
        logger.warning("workspace_changed 广播失败", exc_info=True)
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


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download", summary="下载产物文件")
def artifact_download(run_id: str, artifact_id: int):
    """P2-21：产物下载（桌面态「另存」需要一个**可下载 URL**——此前不存在）。

    只服务**已登记的交付物**（不暴露工作区任意文件）。
    """
    from fastapi.responses import FileResponse

    from app.core.workspace import get_workspace_dir
    from app.services.workspace import artifacts as art

    items = art.list_artifacts(run_id)
    target = next((a for a in items if a["id"] == artifact_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    # **W0-03 / AUD-C09（路径穿越 → 任意文件读取）**
    # 此前 ``get_workspace_dir() / str(target["path"])``：
    #   - ``target["path"]`` 是**绝对路径**时，``Path("/ws") / "/etc/passwd"``
    #     → ``/etc/passwd``（绝对路径**胜出**）→ 读���服务器上任意文件；
    #   - ``../`` 同样可逃逸；
    #   - 且用的是**全局当前工作区**而非 run 绑定的工作区 → 属于历史工作区的产物**必然 404**。
    # 现在：先解析到**该产物所属工作区**根下，再用 ``is_relative_to`` 校验。
    from pathlib import Path as _P

    ws_root = _P(_ws_root(target.get("workspace_id"))).resolve()
    path = (ws_root / str(target["path"])).resolve()
    if not path.is_relative_to(ws_root):
        raise HTTPException(status_code=403, detail="产物路径越界")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件不存在")
    return FileResponse(
        path,
        media_type=target.get("mime") or "application/octet-stream",
        filename=target.get("title") or path.name,
    )


@router.post("/runs/{run_id}/artifacts/{artifact_id}/save-as", summary="产物另存到指定位置")
def artifact_save_as(run_id: str, artifact_id: int, payload: dict = Body(default_factory=dict)) -> dict:
    dest = payload.get("dest")
    if not dest:
        raise HTTPException(status_code=422, detail="缺少 dest")
    # P1-02：dest 必须走**与 revert 同一套**权限判定。
    # 此前 dest 直接进 shutil.copy2、无任何路径限制 → 可写任意绝对路径，
    # 与 revert 端点的策略**不对称**（同一份代码里两套安全标准）。
    # 桌面形态下 ask 会走审批通道（与 revert 一致）；Web 形态无审批通道 → 直接拒绝。
    from app.services.security.permissions import PermissionRequest, PermissionService

    check = PermissionService.instance().enforce(
        PermissionRequest(tool="write_file", path=str(dest)),
        run_id=run_id,
    )
    if not check.allowed:
        raise AppError(
            ErrorCode.PERMISSION,
            f"另存被权限策略拒绝（{check.reason}）",
            status_code=403,
        )
    try:
        return art.save_as(artifact_id, _ws_root(payload.get("workspace_id")), dest)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

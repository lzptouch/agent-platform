"""扩展层 API（S6）：角色 / 插件 / 黑板 / 消息。"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from app.api.deps import get_orchestration_service
from app.core.config import settings
from app.services.chains.skills import scanner
from app.services.chains.skills.plugins import PluginError, PluginManager
from app.services.exec.team.blackboard import BoardError, BlackboardService
from app.services.exec.team.messaging import MessageService
from app.services.exec.team.roles import RoleError, get_role_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extensions"])


# --------------------------------------------------------------------------- #
# 多 Agent 编排（P2-09 路 B）
# --------------------------------------------------------------------------- #
@router.post("/orchestrate", summary="多 Agent 编排（parallel / sequential / review）")
def orchestrate(
    payload: dict = Body(default_factory=dict),
    svc=Depends(get_orchestration_service),
) -> dict:
    """把整体任务拆给多个子 Agent 执行。

    - ``subtasks[].deps`` 用**子任务下标**（黑板模式下自动翻译成黑板项 id）；
    - 传 ``board_id`` 时子任务登记为黑板任务项，状态随执行流转
      （pending → running → done/failed），依赖未完成的项不会被启动；
    - 响应里的 ``main_context`` **只含压缩通知**——子任务原始推理不进主上下文。
    """
    try:
        return svc.orchestrate(
            task=str(payload.get("task") or ""),
            subtasks=list(payload.get("subtasks") or []),
            mode=str(payload.get("mode") or "parallel"),
            board_id=(str(payload["board_id"]) if payload.get("board_id") else None),
            reviewer=str(payload.get("reviewer") or "reviewer"),
            model=(str(payload["model"]) if payload.get("model") else None),
            agent_mode=str(payload.get("agent_mode") or "work"),
            skills=(list(payload["skills"]) if payload.get("skills") else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# 角色
# --------------------------------------------------------------------------- #
@router.get("/roles", summary="角色列表")
def list_roles(include_disabled: bool = Query(default=True)) -> dict:
    svc = get_role_service()
    svc.sync_builtin_roles()  # 保证 S5 内置角色在表里
    return {"items": [r.as_dict() for r in svc.list(include_disabled=include_disabled)]}


@router.post("/roles", status_code=201, summary="创建角色")
def create_role(payload: dict = Body(default_factory=dict)) -> dict:
    svc = get_role_service()
    try:
        role = svc.create(
            str(payload.get("name", "")),
            title=str(payload.get("title", "")),
            identity=str(payload.get("identity", "")),
            expertise=list(payload.get("expertise") or []),
            boundaries=list(payload.get("boundaries") or []),
            workflow=list(payload.get("workflow") or []),
            output_style=str(payload.get("output_style", "")),
            tools=list(payload.get("tools") or []),
            skills=list(payload.get("skills") or []),
            model_tier=str(payload.get("model_tier", "standard")),
        )
    except RoleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return role.as_dict()


@router.patch("/roles/{role_id}", summary="更新角色（不可改名）")
def update_role(role_id: int, payload: dict = Body(default_factory=dict)) -> dict:
    svc = get_role_service()
    try:
        role = svc.update(role_id, **payload)
    except RoleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return role.as_dict()


@router.delete("/roles/{role_id}", summary="删除角色")
def delete_role(role_id: int) -> dict:
    svc = get_role_service()
    try:
        return {"ok": svc.delete(role_id)}
    except RoleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# 插件
# --------------------------------------------------------------------------- #
def _plugin_manager() -> PluginManager:
    root = Path(settings.data_dir) / "extensions"
    root.mkdir(parents=True, exist_ok=True)
    return PluginManager(root)


@router.get("/plugins", summary="已安装插件列表（含扫描结果）")
def list_plugins() -> dict:
    return {"items": _plugin_manager().list_plugins()}


@router.post("/plugins/scan", summary="扫描本地插件目录（不安装）")
def scan_plugin(payload: dict = Body(default_factory=dict)) -> dict:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=422, detail="缺少 path")
    target = Path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    result = scanner.scan_directory(target)
    return {
        **result.as_dict(),
        "requires_confirmation": scanner.needs_confirmation(result),
        "rejected_by_default": scanner.should_reject(result),
    }


def _reload_skills(request: Request) -> None:
    """P2-22：插件安装后重载技能（当前进程立即生效，无需重启）。"""
    try:
        manager = getattr(request.app.state, "skill_manager", None)
        if manager is None:
            return
        manager.reload()
    except Exception as exc:  # noqa: BLE001 - reload 失败不应让安装回滚
        logger.warning("技能重载失败（新技能需重启后生效）: %s", exc)

@router.post("/plugins/install", summary="安装插件包（原子切换）")
def install_plugin(
    request: Request,
    payload: dict = Body(default_factory=dict),
) -> dict:
    """从 zip 字节安装（``content_b64``）或从本地目录安装（``path``）。"""
    import base64
    import shutil
    import tempfile

    mgr = _plugin_manager()
    confirm = bool(payload.get("confirm", False))
    # 插件技能装进**自定义技能目录**（用户数据目录），绝不写源码树
    # （`settings.skills_dir` 是内置技能目录，是只读源）。
    skills_dir = Path(settings.custom_skills_dir)

    content_b64 = payload.get("content_b64")
    if content_b64:
        try:
            data = base64.b64decode(str(content_b64))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"content_b64 解码失败: {exc}") from exc
        try:
            result = mgr.install_from_zip(data, confirm=confirm, skills_dir=skills_dir)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail=f"不是合法的 zip 包: {exc}") from exc
        except PluginError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # P2-22：安装成功后**当前进程**立即加载新技能（此前需重启进程）。
        _reload_skills(request)
        return result.as_dict()

    path = str(payload.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=422, detail="需要 content_b64 或 path")
    src = Path(path)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    tmp = Path(tempfile.mkdtemp(prefix="plugin-src-"))
    try:
        shutil.copytree(src, tmp / "pkg")
        result = mgr._install_dir(tmp / "pkg", confirm=confirm, skills_dir=skills_dir)
        return result.as_dict()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/plugins/rollback", summary="回滚插件到上一版本")
def rollback_plugin(payload: dict = Body(default_factory=dict)) -> dict:
    name = str(payload.get("name", "")).strip()
    version = str(payload.get("version", "")).strip()
    if not name or not version:
        raise HTTPException(status_code=422, detail="需要 name 与 version")
    try:
        return _plugin_manager().rollback(name, version).as_dict()
    except PluginError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# 黑板与消息
# --------------------------------------------------------------------------- #
@router.get("/boards/{board_id}/items", summary="黑板任务项")
def board_items(board_id: str) -> dict:
    svc = BlackboardService()
    return {"items": [i.as_dict() for i in svc.list_items(board_id)]}


@router.post("/boards/{board_id}/items", status_code=201, summary="新增黑板任务项")
def create_board_item(board_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    svc = BlackboardService()
    try:
        item = svc.create_item(
            board_id,
            str(payload.get("title", "")),
            detail=str(payload.get("detail", "")),
            deps=list(payload.get("deps") or []),
            assignee=payload.get("assignee"),
        )
    except BoardError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return item.as_dict()


@router.post("/boards/{board_id}/items/{item_id}/complete", summary="完成任务项（触发重算）")
def complete_board_item(board_id: str, item_id: int, payload: dict = Body(default_factory=dict)) -> dict:
    svc = BlackboardService()
    try:
        # **W0-07**：传入 board_id → 服务层按板精确匹配（防跨板越权）
        items = svc.complete(item_id, result=payload.get("result") or {}, board_id=board_id)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"items": [i.as_dict() for i in items]}


@router.get("/boards/{board_id}/messages", summary="黑板消息与通知")
def board_messages(
    board_id: str,
    to_role: str | None = Query(default=None),
    notifications_only: bool = Query(default=False),
) -> dict:
    msgs = MessageService().list(board_id, to_role=to_role, notifications_only=notifications_only)
    return {"items": [m.as_dict() for m in msgs]}

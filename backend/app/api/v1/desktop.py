"""桌面端接口（Agent Desktop）。

端点与设计文档 ``doc/design/05-数据模型与API设计.md`` §2 一一对应：

===== ==========================================================
 D1   GET  /desktop/status
 D2   GET  /desktop/preferences
 D3   PUT  /desktop/preferences
 D4   GET  /desktop/workspace
 D5   PUT  /desktop/workspace
 D6   GET  /desktop/events            （SSE：后端 → 壳）
 D7   GET  /desktop/components
 D8   POST /desktop/shutdown
 D9   GET  /desktop/permissions
 D10  PUT  /desktop/permissions
 D11  POST /desktop/permissions/decision
 D14  POST /desktop/scheduler/resume-scan
===== ==========================================================

运行控制（中止 / 介入转向）挂在 ``/runs/{id}`` 下，见 ``runs.py``。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_desktop_service, get_permission_service, get_scheduler_service
from app.desktop.events import bus
from app.services.desktop_service import DesktopService
from app.services.security.permissions import DECISIONS, PermissionService
from app.services.scheduler_service import SchedulerService

router = APIRouter(prefix="/desktop", tags=["desktop"])

EVENT_POLL_INTERVAL = 0.3
EVENT_MAX_SECONDS = 3600


# ---------------------------------------------------------------------- #
# D1 / D7  运行态
# ---------------------------------------------------------------------- #
@router.get("/status", summary="桌面运行态快照")
def desktop_status(
    request: Request,
    desktop: DesktopService = Depends(get_desktop_service),
) -> dict:
    scheduler_health: dict[str, Any] = {}
    scheduler = getattr(request.app.state, "scheduler_service", None)
    if scheduler is not None:
        try:
            scheduler_health = scheduler.health()
        except Exception:  # noqa: BLE001 - 状态查询失败不应影响主响应
            scheduler_health = {}
    status = desktop.status(scheduler_health)
    permissions = getattr(request.app.state, "permission_service", None)
    if permissions is not None:
        status["security"]["permission_level"] = permissions.effective_level()
    return status


@router.get("/components", summary="组件安装状态")
def desktop_components(desktop: DesktopService = Depends(get_desktop_service)) -> dict:
    return desktop.components()


# ---------------------------------------------------------------------- #
# D2 / D3  配置
# ---------------------------------------------------------------------- #
@router.get("/preferences", summary="读取桌面配置")
def get_preferences(desktop: DesktopService = Depends(get_desktop_service)) -> dict:
    return desktop.get_preferences()


@router.put("/preferences", summary="更新桌面配置")
def update_preferences(
    payload: dict = Body(default_factory=dict),
    desktop: DesktopService = Depends(get_desktop_service),
) -> dict:
    try:
        preferences = desktop.update_preferences(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "preferences": preferences}


# ---------------------------------------------------------------------- #
# D4 / D5  工作区
# ---------------------------------------------------------------------- #
@router.get("/workspace", summary="当前工作区")
def get_workspace(desktop: DesktopService = Depends(get_desktop_service)) -> dict:
    return desktop.get_workspace()


@router.put("/workspace", summary="切换工作区（立即生效）")
def set_workspace(
    payload: dict = Body(default_factory=dict),
    desktop: DesktopService = Depends(get_desktop_service),
) -> dict:
    path = str(payload.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path")
    try:
        result = desktop.set_workspace(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bus.publish("workspace_changed", workspace_dir=result["workspace_dir"])
    return result


# ---------------------------------------------------------------------- #
# D6  事件流（后端 → 壳）
# ---------------------------------------------------------------------- #
@router.get("/events", summary="桌面事件流（SSE）")
def desktop_events(
    after_id: int = Query(default=0, ge=0),
    max_events: int | None = Query(default=None, ge=1),
) -> StreamingResponse:
    """桌面事件流（SSE：后端 → 桌面壳）。

    ``max_events`` 是**有界模式**：发满指定条数后结束。
    它不是"测试专用开关"——只取前 N 条的客户端（冒烟脚本、一次性诊断）
    不必自己掐断连接；它同时也是本端点**可测**的前提：
    Starlette 的 ``TestClient`` 会先把响应体收完再返回，
    对无限流端点而言，无界模式在测试里必然挂死。

    **P4-09 · 形态限制（明确写进 API 契约）**：
    本端点是**桌面壳专用**的事件通道（壳通过 preload 消费后转发给渲染进程）。
    **Web 形态不消费这条 SSE** —— 因此
    ``permission_requested`` / ``workspace_changed`` / ``scheduler_rescued``
    三类事件在 **Web 端不可见**；Web 端审批走
    ``GET /api/v1/permissions/decisions`` 的**轮询**（默认 2s），
    权限卡仍会出现，只是**延迟上限约 2s**（而非桌面端的即时推送）。
    """
    def event_stream():
        cursor = after_id
        deadline = time.monotonic() + EVENT_MAX_SECONDS
        sent = 0
        yield _sse({"type": "hello", "protocol": 1, "backend_version": _version()})
        sent += 1
        if max_events is not None and sent >= max_events:
            return
        while time.monotonic() < deadline:
            for event in bus.since(cursor):
                cursor = int(event.get("id", cursor))
                yield _sse(event)
                sent += 1
                if max_events is not None and sent >= max_events:
                    return
            yield _sse({"type": "heartbeat", "ts": _now()})
            sent += 1
            if max_events is not None and sent >= max_events:
                return
            time.sleep(EVENT_POLL_INTERVAL)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version() -> str:
    from app.core.config import settings

    return settings.app_version


# ---------------------------------------------------------------------- #
# D8  优雅退出
# ---------------------------------------------------------------------- #
@router.post("/shutdown", summary="请求后端优雅退出")
def desktop_shutdown() -> dict:
    from app.desktop import launcher

    ok = launcher.request_shutdown()
    return {
        "ok": True,
        "message": "shutdown requested" if ok else "当前不是桌面 sidecar 模式，已忽略",
    }


# ---------------------------------------------------------------------- #
# D9 / D10 / D11  权限
# ---------------------------------------------------------------------- #
@router.get("/permissions", summary="读取三态权限规则")
def get_permissions(
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    return {
        "rules": permissions.list_rules(),
        "effective_level": permissions.effective_level(),
        "sandbox_available": __import__("app.services.security.sandbox", fromlist=["probe"]).probe().available,
    }


@router.put("/permissions", summary="更新某条权限规则")
def update_permission(
    payload: dict = Body(default_factory=dict),
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    scope = str(payload.get("scope", "")).strip()
    target = str(payload.get("target", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if decision not in DECISIONS:
        raise HTTPException(status_code=422, detail=f"未知的决定: {decision}")
    try:
        rule = permissions.set_rule(scope, target, decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "rule": rule, "effective_level": permissions.effective_level()}


@router.post("/permissions/decision", summary="对一次待确认操作给出临时决定")
def permission_decision(
    payload: dict = Body(default_factory=dict),
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    decision = str(payload.get("decision", "")).strip()
    scope = str(payload.get("scope", "")).strip()
    target = str(payload.get("target", "")).strip()
    if decision not in ("once", "always", "deny"):
        raise HTTPException(status_code=422, detail="decision 必须是 once / always / deny")
    if not scope or not target:
        # **AUD2-M08**：此前 scope/target 缺失时**静默返回 ok=True**（什么都没做）
        raise HTTPException(status_code=422, detail="缺少 scope / target")
    # **W1-06 / AUD2-H22（「仅此一次」被写成永久规则）**
    # 此前三者都**落库**：``once`` 被映射成 ``ask`` → 用户选「仅此一次」，
    # 实际变成该目标此后**每次都要审批**的**永久规则**（与 F-SEC-13
    # 「会话级决定不落库」直接冲突）。
    # 现在：**只有 ``always`` / ``deny`` 才落库**；``once`` 不写规则表。
    if decision in ("always", "deny"):
        try:
            permissions.set_rule(scope, target, "allow" if decision == "always" else "deny")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    # decision == "once" → **不写规则表**（一次性授权由会话内的 pending decision 通道承担）
    return {
        "ok": True,
        "decision": decision,
        "expires_at": None,
        "persisted": decision in ("always", "deny"),
    }


# ---------------------------------------------------------------------- #
# D14  唤醒补跑
# ---------------------------------------------------------------------- #
@router.post("/scheduler/resume-scan", summary="扫描并补跑错过的定时任务")
def resume_scan(
    payload: dict = Body(default_factory=dict),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> dict:
    raw_since = str(payload.get("missed_since", "")).strip()
    if raw_since:
        try:
            since = datetime.fromisoformat(raw_since)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="missed_since 必须是 ISO8601") from exc
    else:
        since = datetime.now(timezone.utc)

    result = scheduler.rescue_missed_runs(since=since)
    bus.publish("scheduler_rescued", **{k: v for k, v in result.items() if k != "items"})
    return {"ok": True, **result}

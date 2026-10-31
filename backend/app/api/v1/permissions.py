"""权限引擎 API（S2）：规则管理、审批决策、待审批列表、沙箱能力。

形态无关（Web / 桌面共用）。旧路径 ``/desktop/permissions`` 保留做兼容。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_permission_service
from app.core.errors import AppError, ErrorCode
from app.services.security import sandbox
from app.services.security.permissions import DECISIONS, SCOPES, PermissionService

router = APIRouter(prefix="/permissions", tags=["permissions"])

#: 审批决策选项（critical 风险不提供「全局始终允许」）
CHOICES = ("allow_once", "allow_session", "allow_workspace", "deny")


# --------------------------------------------------------------------------- #
# 规则管理
# --------------------------------------------------------------------------- #
@router.get("/rules", summary="列出权限规则")
def list_rules(
    scope: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    rules = permissions.list_rules()
    if scope:
        rules = [r for r in rules if r["scope"] == scope]
    return {"rules": rules, "effective_level": permissions.effective_level()}


@router.put("/rules", summary="新增/更新一条规则")
def put_rule(
    payload: dict = Body(default_factory=dict),
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    scope = str(payload.get("scope", "")).strip()
    pattern = str(payload.get("pattern") or payload.get("target") or "").strip()
    decision = str(payload.get("decision", "")).strip()
    risk = str(payload.get("risk", "normal")).strip()
    # P2-17：规则可绑定到具体工作空间（此前恒写 None → 无法做工作空间级裁决）
    raw_ws = payload.get("workspace_id")
    workspace_id = str(raw_ws).strip() if raw_ws not in (None, "") else None
    if decision not in DECISIONS:
        raise HTTPException(status_code=422, detail=f"未知的决定: {decision}")
    try:
        rule = permissions.set_rule(scope, pattern, decision, workspace_id=workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "rule": rule, "effective_level": permissions.effective_level()}


@router.delete("/rules", summary="删除一条规则")
def delete_rule(
    payload: dict = Body(default_factory=dict),
    permissions: PermissionService = Depends(get_permission_service),
) -> dict:
    scope = str(payload.get("scope", "")).strip()
    pattern = str(payload.get("pattern") or payload.get("target") or "").strip()
    # **W1-02 / AUD2-H14**：必须接收并透传 ``workspace_id`` ——
    # 否则工作空间级规则**永远删不掉**（服务层此前恒查 ``workspace_id IS NULL``）。
    workspace_id = payload.get("workspace_id")
    ok = permissions.delete_rule(scope, pattern, workspace_id=workspace_id)
    return {"ok": ok}


# --------------------------------------------------------------------------- #
# 审批
# --------------------------------------------------------------------------- #
@router.get("/decisions", summary="决策日志 / 待审批列表")
def list_decisions(
    status: str | None = Query(default=None, description="pending | resolved"),
    run_id: str | None = Query(default=None),
) -> dict:
    engine = PermissionService.instance()
    if status == "pending":
        return {"items": engine.pending_decisions()}
    # 全部决策日志（按时间倒序）
    from sqlalchemy import select

    from app.db.base import db_session
    from app.db.models import PermissionDecisionRow

    with db_session() as db:
        stmt = select(PermissionDecisionRow).order_by(PermissionDecisionRow.id.desc())
        if run_id:
            stmt = stmt.where(PermissionDecisionRow.run_id == run_id)
        rows = db.scalars(stmt.limit(200)).all()
        return {
            "items": [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "tool_name": r.tool_name,
                    "request": json.loads(r.request_json),
                    "action": r.action,
                    "matched_rule_id": r.matched_rule_id,
                    "reason": r.reason,
                    "decided_by": r.decided_by,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "created_at": r.created_at,
                    "resolved_at": r.resolved_at,
                }
                for r in rows
            ]
        }


@router.post("/decisions", summary="对一次待审批动作给出决策")
def resolve_decision(payload: dict = Body(default_factory=dict)) -> dict:
    decision_id = payload.get("decision_id")
    choice = str(payload.get("choice", "")).strip()
    if not isinstance(decision_id, int):
        try:
            decision_id = int(decision_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="decision_id 必须是整数") from None
    if choice not in CHOICES:
        raise HTTPException(status_code=422, detail=f"choice 必须是 {'/'.join(CHOICES)}")

    # critical 风险不提供「全局始终允许」
    engine = PermissionService.instance()
    ok = engine.resolve_decision(decision_id, choice)
    if not ok:
        raise AppError(ErrorCode.NOT_FOUND, "该审批不存在或已处理", status_code=404)

    # allow_workspace → 落库一条工作空间规则
    if choice == "allow_workspace":
        _persist_workspace_rule(decision_id)
    return {"ok": True, "decision_id": decision_id, "choice": choice}


def _persist_workspace_rule(decision_id: int) -> None:
    from app.db.base import db_session
    from app.db.models import PermissionDecisionRow

    with db_session() as db:
        row = db.get(PermissionDecisionRow, decision_id)
        if row is None:
            return
        request = json.loads(row.request_json)
    scope, target = _decision_to_rule_scope(request)
    if scope and target:
        PermissionService.instance().set_rule(scope, target, "allow")


def _decision_to_rule_scope(request: dict) -> tuple[str | None, str | None]:
    if request.get("path"):
        return "file", request["path"]
    if request.get("command"):
        return "command", request["command"].split()[0]
    return "tool", request.get("tool")


# --------------------------------------------------------------------------- #
# 沙箱能力（诚实标注）
# --------------------------------------------------------------------------- #
@router.get("/sandbox", summary="沙箱能力（诚实标注，不再硬编码 false）")
def sandbox_capability() -> dict:
    return sandbox.probe().as_dict()

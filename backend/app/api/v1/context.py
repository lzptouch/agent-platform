"""上下文经济性与成本端点（S5 / WP-5.6）。

- ``GET /runs/{run_id}/cost``：一次运行的逐次调用明细与合计；
- ``GET /sessions/{session_id}/context``：会话上下文占用（按最近 N 轮估算）；
- ``GET /memories`` / ``POST /memories`` / ``DELETE /memories``：记忆管理。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from app.core.config import settings
from app.core.pricing import price_table
from app.services.exec import memory as mem
from app.services.exec.accounting import cost_percentiles, run_cost_detail

router = APIRouter(tags=["context"])


# --------------------------------------------------------------------------- #
# 成本
# --------------------------------------------------------------------------- #
@router.get("/runs/{run_id}/cost", summary="一次运行的成本明细")
def run_cost(run_id: str) -> dict:
    """逐次调用明细 + 合计（可加总核对）。"""
    detail = run_cost_detail(run_id)
    detail["percentiles"] = cost_percentiles()
    detail["pricing"] = price_table()
    return detail


@router.get("/cost/estimate", summary="发起前的消耗区间（p50~p90）")
def cost_estimate(model: str | None = Query(default=None)) -> dict:
    return {"percentiles": cost_percentiles(model), "pricing": price_table()}


# --------------------------------------------------------------------------- #
# 上下文
# --------------------------------------------------------------------------- #
@router.get("/sessions/{session_id}/context", summary="会话上下文占用")
def session_context(session_id: str, turns: int = Query(default=20, ge=1, le=200)) -> dict:
    """按最近 N 轮估算上下文占用（token / 字符 / 比例）。"""
    from app.db.base import db_session
    from app.db.models import MessageRow
    from app.services.exec.context import ContextBudget, estimate_tokens
    from sqlalchemy import select

    with db_session() as db:
        rows = db.scalars(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id.desc())
            .limit(turns)
        ).all()
    messages = [
        {"role": r.role, "content": r.content or ""}
        for r in reversed(rows)
    ]
    budget = ContextBudget.for_model(settings.default_model, settings.context_budget_ratio)
    usage = budget.usage(messages)
    return {
        "session_id": session_id,
        "turns": len(messages),
        "usage": usage,
        "window": budget.window,
        "thresholds": {
            "compact": settings.context_compact_threshold,
            "summary": settings.context_summary_threshold,
        },
    }


# --------------------------------------------------------------------------- #
# 记忆
# --------------------------------------------------------------------------- #
@router.get("/memories", summary="列出记忆（按作用域）")
def list_memories(scope: str | None = Query(default=None)) -> dict:
    mem.refresh_index(scope)
    items = mem.list_memories(scope)
    return {
        "items": [i.as_dict() for i in items],
        "max_injected": settings.context_memory_max,
        "enabled": settings.context_memory_enabled,
    }


@router.post("/memories", status_code=201, summary="写入一条记忆")
def create_memory(payload: dict = Body(default_factory=dict)) -> dict:
    scope = str(payload.get("scope", "project")).strip()
    name = str(payload.get("name", "")).strip()
    content = str(payload.get("content", "")).strip()
    if scope not in mem.SCOPES:
        raise HTTPException(status_code=422, detail=f"scope 必须是 {'/'.join(mem.SCOPES)}")
    if not name or not content:
        raise HTTPException(status_code=422, detail="name 与 content 均不能为空")
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        raise HTTPException(status_code=422, detail="tags 必须是数组")
    item = mem.write_memory(scope, name, content, tags=[str(t) for t in tags])
    return item.as_dict()


@router.delete("/memories", summary="删除一条记忆")
def delete_memory(payload: dict = Body(default_factory=dict)) -> dict:
    scope = str(payload.get("scope", "project")).strip()
    path = str(payload.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=422, detail="缺少 path")
    return {"ok": mem.delete_memory(scope, path)}


@router.post("/memories/clear", summary="清空某作用域的记忆")
def clear_memories(payload: dict = Body(default_factory=dict)) -> dict:
    scope = str(payload.get("scope", "project")).strip()
    if scope not in mem.SCOPES:
        raise HTTPException(status_code=422, detail=f"scope 必须是 {'/'.join(mem.SCOPES)}")
    return {"removed": mem.clear_memories(scope)}

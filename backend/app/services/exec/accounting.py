"""LLM 调用计量（S5 / WP-5.5）。

- 每次调用写一行 ``llm_calls``（含**单价快照**）；
- 聚合到 ``runs``（prompt_tokens / completion_tokens / llm_calls / estimated_cost）；
- 统计"同类任务历史消耗 p50~p90"（用于任务前显示区间）。

**旁路写入**：计量失败只记告警，不影响主流程（回滚纪律：计量可留空）。
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.pricing import calculate_cost
from app.db.base import db_session
from app.db.models import LlmCallRow, RunRow, utc_now

logger = logging.getLogger(__name__)


@dataclass
class CallUsage:
    """一次调用的用量。"""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    role: str = "agent"
    provider: str = "dashscope"


def record_call(
    usage: CallUsage,
    *,
    run_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """写入一条计量记录，返回含成本与快照的记录。"""
    cost, snapshot = calculate_cost(
        usage.model,
        usage.prompt_tokens,
        usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
    )
    try:
        with db_session() as db:
            row = LlmCallRow(
                run_id=run_id,
                session_id=session_id,
                model=usage.model,
                provider=usage.provider,
                role=usage.role,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cached_tokens=usage.cached_tokens,
                latency_ms=usage.latency_ms,
                price_snapshot=json.dumps(snapshot, ensure_ascii=False),
                cost=cost,
            )
            db.add(row)
            db.flush()
    except Exception as exc:  # noqa: BLE001 —— 计量失败不阻断主流程
        logger.warning("LLM 计量写入失败（不影响主流程）: %s", exc)
    return {"cost": cost, "price_snapshot": snapshot, **usage.__dict__}


def aggregate_run(run_id: str) -> dict:
    """聚合某次 run 的计量（**纯读**，不写 ``runs`` 行）。

    **W2-03 / AUD2-H06（乐观锁版本冲突）修复**

    此前本函数会在**自己的 session** 里写回 ``runs`` 行（``prompt_tokens`` 等），
    而 ``RunService.finish()`` 在**外层 session** 里已经持有该行的**旧版本**
    → 内层提交后 ``version_id`` 自增 → 外层 flush 时
    ``UPDATE ... WHERE id=? AND version_id=<旧值>`` **匹配 0 行**
    → ``StaleDataError: UPDATE statement on table 'runs' expected to update 1 row(s)``
    → **整个 run 的收尾失败**（终态写不进去，run 卡在 running）。

    该缺陷此前是**潜伏**的：``llm_calls.run_id`` 恒为 NULL（见 ``AUD-C02``）→
    本函数在 ``if not calls`` 处提前 return → 从不碰 ``runs`` 行。
    修复 run_id 归属后被暴露出来。

    现在改为**纯读**：``runs`` 行由 ``RunService.finish()`` 作为**唯一写入方**落账
    （它本来就会写这四个字段），语义更清晰，也消除了双写与版本冲突。
    """
    with db_session() as db:
        calls = db.scalars(select(LlmCallRow).where(LlmCallRow.run_id == run_id)).all()
        if not calls:
            return {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0}
        prompt_tokens = sum(c.prompt_tokens for c in calls)
        completion_tokens = sum(c.completion_tokens for c in calls)
        cost = round(sum(c.cost for c in calls), 8)
        return {
            "llm_calls": len(calls),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost": cost,
        }


def run_cost_detail(run_id: str) -> dict:
    """一次 run 的成本明细（逐次调用）。"""
    with db_session() as db:
        calls = db.scalars(
            select(LlmCallRow).where(LlmCallRow.run_id == run_id).order_by(LlmCallRow.id)
        ).all()
        items = [
            {
                "id": c.id,
                "model": c.model,
                "provider": c.provider,
                "role": c.role,
                "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens,
                "cached_tokens": c.cached_tokens,
                "latency_ms": c.latency_ms,
                "cost": c.cost,
                "price_snapshot": json.loads(c.price_snapshot or "{}"),
                "created_at": c.created_at,
            }
            for c in calls
        ]
        return {
            "items": items,
            "totals": {
                "llm_calls": len(items),
                "prompt_tokens": sum(i["prompt_tokens"] for i in items),
                "completion_tokens": sum(i["completion_tokens"] for i in items),
                "estimated_cost": round(sum(i["cost"] for i in items), 8),
            },
        }


def cost_percentiles(model: str | None = None, *, limit: int = 50) -> dict:
    """同类任务历史消耗区间（p50~p90），用于任务前展示。"""
    with db_session() as db:
        stmt = select(LlmCallRow.cost)
        if model:
            stmt = stmt.where(LlmCallRow.model == model)
        costs = [c for c in db.scalars(stmt.limit(limit * 4)).all() if c is not None]
    if not costs:
        return {"p50": None, "p90": None, "samples": 0}
    costs.sort()
    p50 = statistics.median(costs)
    idx = min(len(costs) - 1, int(len(costs) * 0.9))
    return {
        "p50": round(p50, 8),
        "p90": round(costs[idx], 8),
        "samples": len(costs),
    }


class Timer:
    """调用计时器（上下文管理器）。"""

    def __init__(self) -> None:
        self.started = 0.0
        self.elapsed_ms = 0

    def __enter__(self) -> "Timer":
        self.started = time.monotonic()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed_ms = int((time.monotonic() - self.started) * 1000)

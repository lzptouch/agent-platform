"""系统 / 健康检查接口（聚合四链路状态）。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_research_manager, get_scheduler_service, get_skill_manager
from app.core.config import settings
from app.db.base import check_db
from app.services.research.research_manager import ResearchManager
from app.services.scheduler_service import SchedulerService
from app.services.mcp_manager import MCPManager
from app.services.skill_manager import SkillManager

router = APIRouter(tags=["system"])


def _percentile(values: list[int], pct: float) -> int | None:
    """**插值法**分位数（P4-07）——与 ``numpy.percentile`` 默认线性插值一致。

    此前用下标法（``sorted[len // 2]``），偶数样本时会取偏大的那个，
    与常见统计口径不符。
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return int(round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac))


@router.get("/metrics", summary="运行指标（并发 / 成功率 / 耗时 / 成本 / MCP 连接）")
def metrics() -> dict:
    """运行指标快照（S7 / WP-7.8）。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.db.base import db_session
    from app.db.models import LlmCallRow, RunRow
    from app.services.chains.mcp.transport import pool_size
    from app.services.run_service import TERMINAL_STATUSES

    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(hours=24)).isoformat()

    with db_session() as db:
        running = db.scalar(
            select(func.count()).select_from(RunRow).where(RunRow.status == "running")
        ) or 0
        total_today = db.scalar(
            select(func.count()).select_from(RunRow).where(RunRow.created_at >= day_ago)
        ) or 0
        success_today = db.scalar(
            select(func.count()).select_from(RunRow).where(
                RunRow.created_at >= day_ago, RunRow.status == "success"
            )
        ) or 0
        # P4-07：终态口径——``success_rate`` 的分母是**全部终态 run**
        # （可从 runs 表复算）；``skipped`` 另计。
        terminal_today = db.scalar(
            select(func.count()).select_from(RunRow).where(
                RunRow.created_at >= day_ago, RunRow.status.in_(TERMINAL_STATUSES)
            )
        ) or 0
        skipped_today = db.scalar(
            select(func.count()).select_from(RunRow).where(
                RunRow.created_at >= day_ago, RunRow.status == "skipped"
            )
        ) or 0
        durations = [d for d in db.scalars(
            select(RunRow.duration_ms).where(
                RunRow.duration_ms.isnot(None), RunRow.created_at >= day_ago
            )
        ).all()]
        llm_today = db.scalar(
            select(func.count()).select_from(LlmCallRow).where(LlmCallRow.created_at >= day_ago)
        ) or 0
        cost_today = db.scalar(
            select(func.coalesce(func.sum(LlmCallRow.cost), 0)).where(LlmCallRow.created_at >= day_ago)
        ) or 0.0

    # P4-07：字段名与口径一致——
    # ① 「最近 24 小时」不再叫 ``runs_today``（会被误读为自然日）；
    # ② ``success_rate`` 的分母是**全部终态 run**，并另给「排除 skipped」口径；
    # ③ 分位数改插值法。
    terminal_total = terminal_today
    success_rate = round(success_today / terminal_total, 4) if terminal_total else None
    success_rate_excl = (
        round(success_today / (terminal_total - skipped_today), 4)
        if (terminal_total - skipped_today) > 0 else None
    )
    return {
        "concurrency": {"running": running, "limit": settings.schedule_max_concurrent},
        "success_rate": success_rate,
        "success_rate_excluding_skipped": success_rate_excl,
        "runs_24h": total_today,
        "runs_today": total_today,   # 兼容旧字段（口径见文档）
        "terminal_runs_24h": terminal_total,
        "duration_ms": {
            "samples": len(durations),
            "p50": _percentile(durations, 50),
            "p90": _percentile(durations, 90),
        },
        "llm": {
            "calls_24h": llm_today, "calls_today": llm_today,
            "cost_24h": round(cost_today, 8), "cost_today": round(cost_today, 8),
        },
        "mcp_connections": pool_size(),
        "ts": now.isoformat(),
    }


@router.get("/health", summary="健康检查")
def health(
    manager: SkillManager = Depends(get_skill_manager),
    research: ResearchManager = Depends(get_research_manager),
    scheduler: SchedulerService = Depends(get_scheduler_service),
) -> dict:
    # RAG 状态（Milvus 连接失败不影响健康检查）
    rag_entities = -1
    try:
        from app.services.rag.milvus_store import get_collection

        rag_entities = get_collection().num_entities
    except Exception:
        pass

    # Research 链路检索提供方
    search_provider = "none"
    try:
        from app.services.research.search_client import get_search_client

        search_provider = get_search_client().provider
    except Exception:
        pass

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "skills_loaded": len(manager.list_skills()),
        "api_key_configured": settings.has_api_key,
        "output_dir": str(settings.output_dir),
        "mcp_servers_available": len(MCPManager.SERVER_REGISTRY),
        "rag_collection": settings.milvus_collection,
        "rag_entities": rag_entities,
        "web_search_available": settings.web_search_available,
        "llm_available": settings.llm_available,
        # ---- Research 链路 ----
        "research_enabled": True,
        "research_search_provider": search_provider,
        "research_configured": settings.research_configured,
        "research_total_tasks": len(research.tasks),
        "research_running_tasks": research.running_count(),
        # ---- WorkBuddy 扩展 ----
        "database": "ok" if check_db() else "error",
        "scheduler": scheduler.health(),
    }

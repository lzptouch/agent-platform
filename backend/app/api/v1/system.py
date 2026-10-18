"""系统 / 健康检查接口（聚合四链路状态）。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_research_manager, get_scheduler_service, get_skill_manager
from app.core.config import settings
from app.db.base import check_db
from app.services.research.research_manager import ResearchManager
from app.services.scheduler_service import SchedulerService
from app.services.skill_manager import SkillManager

router = APIRouter(tags=["system"])


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
        "mcp_servers_available": 3,
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

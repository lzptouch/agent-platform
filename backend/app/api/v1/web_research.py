"""Web Research 链路接口（实时网络检索带引用回答）。"""
import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.web_research import (
    WebResearchRequest,
    WebResearchResponse,
    WebResearchStatusResponse,
)
from app.services.web.research_service import web_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web_research", tags=["web_research"])


@router.post("/research", response_model=WebResearchResponse, summary="Web Research 带引用回答 + 引用卡片")
def web_research_endpoint(req: WebResearchRequest):
    try:
        return WebResearchResponse(**web_research(req.query, req.profile, req.output_format))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("web_research 失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=WebResearchStatusResponse, summary="Web Research 链路可用性")
def web_research_status():
    return WebResearchStatusResponse(
        serper_available=settings.web_search_available,
        openai_available=bool(settings.openai_api_key.strip()),
        openai_model=settings.openai_model,
    )

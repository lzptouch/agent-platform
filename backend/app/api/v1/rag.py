"""RAG 链路接口（本地文档检索问答）。"""
import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.rag import (
    IngestResponse,
    RagQueryRequest,
    RagQueryResponse,
    RagStatsResponse,
)
from app.services.rag.embedding import EMBEDDING_DIM, EMBEDDING_MODEL
from app.services.rag.ingest import ingest
from app.services.rag.milvus_store import get_collection
from app.services.rag.rag_chain import format_list_with_markers, rag, retrieval

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query", response_model=RagQueryResponse, summary="本地文档 RAG 问答")
def rag_query(req: RagQueryRequest):
    try:
        references, answer = rag(req.query)
        return RagQueryResponse(query=req.query, references=references, answer=answer)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("rag_query 失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrieval", summary="仅混合检索（不调 LLM）")
def rag_retrieval_only(req: RagQueryRequest):
    try:
        docs = retrieval(req.query, limit=req.limit)
        return {"query": req.query, "documents": docs, "references": format_list_with_markers(docs)}
    except Exception as e:
        logger.exception("rag_retrieval_only 失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest", response_model=IngestResponse, summary="解析 data/pdf/ 并入库 Milvus")
def rag_ingest(recreate: bool = True):
    try:
        return IngestResponse(**ingest(recreate=recreate))
    except Exception as e:
        logger.exception("rag_ingest 失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=RagStatsResponse, summary="RAG collection 状态")
def rag_stats():
    try:
        entities = get_collection().num_entities
    except Exception:
        entities = -1
    return RagStatsResponse(
        collection=settings.milvus_collection,
        entities=entities,
        dense_dim=EMBEDDING_DIM,
        embedding_model=EMBEDDING_MODEL,
        llm_available=settings.llm_available,
    )

"""Agent 运行接口（SSE 流式 + 阻塞式 + Plan 审批 + WR 范式 agent/chat）。"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_run_executor, get_run_service
from app.core.config import AVAILABLE_MODELS, settings
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    ModelInfo,
    ModelsResponse,
    RunRequest,
    RunResult,
)
from app.schemas.run import PlanApproval, PlanRejection, RunOut
from app.services.run_executor import RunExecutor
from app.services.run_service import RunService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/models", response_model=ModelsResponse, summary="可用模型列表")
def list_models() -> ModelsResponse:
    return ModelsResponse(
        default_model=settings.default_model,
        models=[ModelInfo(**m) for m in AVAILABLE_MODELS],
    )


@router.get("/status", summary="Agent 就绪状态")
def status(executor: RunExecutor = Depends(get_run_executor)) -> dict:
    return {
        "ready": executor.agent_service.is_ready(),
        "api_key_configured": settings.has_api_key,
        "default_model": settings.default_model,
        "max_iterations": settings.max_iterations,
    }


@router.post("/run", summary="运行 Agent（SSE 事件流，支持 mode/session/team/plan_first）")
def run_agent(payload: RunRequest, executor: RunExecutor = Depends(get_run_executor)) -> StreamingResponse:
    def event_stream():
        for event in executor.execute_stream(
            payload.prompt,
            mode=payload.mode,
            session_id=payload.session_id,
            team_id=payload.team_id,
            plan_first=payload.plan_first,
            model=payload.model,
            skills=payload.skills,
            enable_mcp=payload.enable_mcp,
            mcp_servers=payload.mcp_servers,
            enable_rag=payload.enable_rag,
            enable_web_research=payload.enable_web_research,
            enable_reflection=payload.enable_reflection,
            trigger="api",
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/run/sync", response_model=RunResult, summary="运行 Agent（阻塞式，便于脚本/测试）")
def run_agent_sync(payload: RunRequest, executor: RunExecutor = Depends(get_run_executor)) -> RunResult:
    result = executor.execute_sync(
        payload.prompt,
        mode=payload.mode,
        session_id=payload.session_id,
        team_id=payload.team_id,
        plan_first=payload.plan_first,
        model=payload.model,
        skills=payload.skills,
        enable_mcp=payload.enable_mcp,
        mcp_servers=payload.mcp_servers,
        enable_rag=payload.enable_rag,
        enable_web_research=payload.enable_web_research,
        enable_reflection=payload.enable_reflection,
        trigger="api",
    )
    return RunResult(
        model=result.get("model", payload.model),
        prompt=payload.prompt,
        rounds=0,
        finished=bool(result.get("finished")),
        files=result.get("files", []),
        error=result.get("error"),
        run_id=result.get("run_id"),
        session_id=result.get("session_id"),
        mode=payload.mode,
        answer=result.get("answer", ""),
    )


@router.post("/runs/{run_id}/approve", response_model=RunOut, summary="批准计划并继续执行")
def approve_run(
    run_id: str,
    payload: PlanApproval,
    executor: RunExecutor = Depends(get_run_executor),
    run_service: RunService = Depends(get_run_service),
) -> RunOut:
    run = run_service.approve_plan(run_id, edited_plan=payload.edited_plan)
    if run is None:
        raise HTTPException(status_code=409, detail="运行不存在或不处于待审批状态")
    executor.resume_after_approval(run_id)
    current = run_service.get_run(run_id)
    assert current is not None
    return current


@router.post("/runs/{run_id}/reject", response_model=RunOut, summary="拒绝计划")
def reject_run(
    run_id: str,
    payload: PlanRejection,
    run_service: RunService = Depends(get_run_service),
) -> RunOut:
    run = run_service.reject_run(run_id, reason=payload.reason)
    if run is None:
        raise HTTPException(status_code=409, detail="运行不存在或不处于待审批状态")
    return run


@router.post("/chat", response_model=AgentChatResponse, summary="WR 范式 Agent（plan→action→(reflection)→answer）")
def agent_chat(req: AgentChatRequest) -> AgentChatResponse:
    """迁移自 webResearch 的销售助手 Agent 端点。"""
    from app.services.agent.service import agent, agent_reflection

    try:
        result = agent_reflection(req.query) if req.reflection else agent(req.query)
        return AgentChatResponse(**result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("agent_chat 失败")
        raise HTTPException(status_code=500, detail=str(e))

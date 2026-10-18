"""深度研究链路 API（自 ``deep_research/app/main.py`` 迁移）。

端点（含前缀 ``/api/v1``）：
- ``GET    /research/health``            链路健康
- ``POST   /research``                   提交任务（后台线程执行）
- ``GET    /research``                   任务列表
- ``GET    /research/{task_id}``         任务状态 + 进度
- ``GET    /research/{task_id}/result``  最终报告
- ``GET    /research/{task_id}/stream``  SSE 进度流
- ``DELETE /research/{task_id}``         删除任务
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_research_manager
from app.schemas.research import (
    ResearchHealth,
    ResearchRequest,
    ResearchSubmitResponse,
    ResearchTaskList,
    ResearchTaskResult,
    ResearchTaskStatus,
)
from app.services.research.research_manager import ResearchManager
from app.services.research.service import run_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])

# SSE 轮询间隔（秒）与单次流上限（秒）
SSE_POLL_INTERVAL = 0.5
SSE_MAX_DURATION = 1800
TERMINAL_STATES = {"completed", "failed"}


# ---------------------------------------------------------------------- #
# 后台任务
# ---------------------------------------------------------------------- #
def run_research_task(
    manager: ResearchManager,
    task_id: str,
    task_text: str,
    config: dict,
) -> None:
    """在线程池中执行研究任务。

    注意：``manager`` / ``task_text`` **显式传参**，不在线程内访问请求上下文
    （后台线程脱离请求作用域，拿不到 ``request.app``）。
    """
    try:
        manager.set_running(task_id)

        def on_progress(stage: str, data: dict) -> None:
            manager.update_progress(task_id, stage, data)

        state = run_research(
            task_text,
            max_workers=config.get("max_workers"),
            on_progress=on_progress,
            config_overrides={
                "max_iterations": config.get("max_iterations"),
                "quality_threshold": config.get("quality_threshold"),
            },
        )
        if state.status == "completed":
            manager.set_completed(task_id, state)
        else:
            manager.set_failed(task_id, state.error_msg or "未知错误")
    except Exception as exc:  # noqa: BLE001 —— 任务异常必须落到任务状态
        logger.exception("研究任务 %s 执行失败", task_id)
        manager.set_failed(task_id, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------- #
# 端点
# ---------------------------------------------------------------------- #
@router.get("/health", response_model=ResearchHealth, summary="Research 链路健康")
def health(manager: ResearchManager = Depends(get_research_manager)) -> ResearchHealth:
    from app.services.research.search_client import get_search_client

    return ResearchHealth.build(
        provider=get_search_client().provider,
        total=len(manager.tasks),
        running=manager.running_count(),
    )


@router.post("", response_model=ResearchSubmitResponse, summary="提交研究任务")
async def submit_research(
    payload: ResearchRequest,
    manager: ResearchManager = Depends(get_research_manager),
) -> ResearchSubmitResponse:
    from app.services.research.search_client import get_search_client

    task_id = manager.create_task(
        payload.task,
        max_workers=payload.max_workers,
        max_iterations=payload.max_iterations,
        quality_threshold=payload.quality_threshold,
    )
    task = manager.get_task(task_id)

    # 快速失败：无检索提供方时立刻给明确结论，避免白等数分钟
    provider = get_search_client().provider
    if provider == "none":
        manager.set_failed(
            task_id,
            "未配置检索服务：请在 .env 设置 BOCHA_API_KEY（推荐）或 SERPER_API_KEY 后重试",
        )
        return ResearchSubmitResponse(
            task_id=task_id,
            status="failed",
            message="提交被拒绝：未配置 BOCHA_API_KEY / SERPER_API_KEY",
            created_at=task["created_at"],
        )

    loop = asyncio.get_running_loop()
    loop.run_in_executor(manager.executor, run_research_task, manager, task_id, payload.task, task["config"])
    return ResearchSubmitResponse(
        task_id=task_id,
        status="pending",
        message=f"研究任务已提交（检索提供方: {provider}），正在启动...",
        created_at=task["created_at"],
    )


@router.get("", response_model=ResearchTaskList, summary="研究任务列表")
def list_research(manager: ResearchManager = Depends(get_research_manager)) -> ResearchTaskList:
    tasks = manager.list_tasks()
    return ResearchTaskList(total=len(tasks), tasks=tasks)


@router.get("/{task_id}", response_model=ResearchTaskStatus, summary="查询任务状态")
def get_research_status(
    task_id: str,
    manager: ResearchManager = Depends(get_research_manager),
) -> ResearchTaskStatus:
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    result = task.get("result") or {}
    return ResearchTaskStatus(
        task_id=task["task_id"],
        status=task["status"],
        progress=task["progress"][-20:],  # 只回传最近 20 条，避免响应过大
        progress_summary=task["progress_summary"],
        original_task=task["original_task"],
        created_at=task["created_at"],
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        quality_score=result.get("quality_score"),
        iteration_count=result.get("iteration_count"),
        error_message=task.get("error"),
    )


@router.get("/{task_id}/result", response_model=ResearchTaskResult, summary="获取研究报告")
def get_research_result(
    task_id: str,
    manager: ResearchManager = Depends(get_research_manager),
) -> ResearchTaskResult:
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if task["status"] not in TERMINAL_STATES:
        raise HTTPException(status_code=202, detail=f"任务尚未完成（当前状态: {task['status']}）")
    result = task.get("result") or {}
    return ResearchTaskResult(
        task_id=task["task_id"],
        status=task["status"],
        report=result.get("report"),
        quality_score=result.get("quality_score"),
        iteration_count=result.get("iteration_count"),
        duration=result.get("duration"),
        metadata={"error": task.get("error")} if task.get("error") else None,
    )


@router.get("/{task_id}/stream", summary="SSE 进度流")
async def stream_research(
    task_id: str,
    manager: ResearchManager = Depends(get_research_manager),
) -> StreamingResponse:
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    async def event_stream():
        sent = 0
        elapsed = 0.0
        while elapsed < SSE_MAX_DURATION:
            current = manager.get_task(task_id)
            if not current:
                break
            progress = current["progress"]
            while sent < len(progress):
                yield f"data: {json.dumps({'type': 'progress', **progress[sent]}, ensure_ascii=False)}\n\n"
                sent += 1
            if current["status"] in TERMINAL_STATES:
                payload = {
                    "type": "final",
                    "status": current["status"],
                    "quality_score": (current.get("result") or {}).get("quality_score"),
                    "iteration_count": (current.get("result") or {}).get("iteration_count"),
                    "error": current.get("error"),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(SSE_POLL_INTERVAL)
            elapsed += SSE_POLL_INTERVAL

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.delete("/{task_id}", summary="删除任务")
def delete_research(
    task_id: str,
    manager: ResearchManager = Depends(get_research_manager),
) -> dict:
    if not manager.get_task(task_id):
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    try:
        manager.delete_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "deleted": True, "deleted_at": datetime.now().isoformat()}

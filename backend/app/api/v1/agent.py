"""Agent 运行接口（SSE 流式 + 阻塞式 + Plan 审批 + WR 范式 agent/chat）。"""

import asyncio
import contextvars
import json
import logging
import threading

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
async def run_agent(
    payload: RunRequest, executor: RunExecutor = Depends(get_run_executor)
) -> StreamingResponse:
    """SSE 事件流。

    **W0-01 / AUD-C01（contextvar 跨线程丢失）修复**

    这里**不能**把同步生成器直接交给 ``StreamingResponse``：
    Starlette 对同步迭代器走 ``iterate_in_threadpool`` → ``anyio.to_thread.run_sync``，
    而 anyio **每次调用**都会在事件循环线程里做一次 ``copy_context()``
    （``anyio/_backends/_asyncio.py:2698``），worker 线程再以 ``context.run(func)``
    执行（``:1100``）→ **生成器体内的 ``contextvar.set()`` 写入的是本次调用的临时副本**，
    随 ``next()`` 返回即丢弃；下一次 ``next()`` 是一次**全新的** ``copy_context()`` → **值全丢**。

    后果（**生产 SSE 路径**上）：产物登记 / 写盘目录绑定 / 变更追踪 / 权限审计归属 /
    工具延迟装载 —— **6 项已声明交付的能力全部失效**（`design/01` 的 F-WS-02/03/05/08、
    F-CTX-01/09、F-SEC-07/14）。

    **修复**：把**整个同步生成器的消费过程**放进**同一个** ``contextvars.Context``
    （``ctx.run``），中间用队列把事件转发回事件循环。
    这样生成器内的 ``set()`` 与后续所有 ``next()`` 共享同一 Context → **全程有效**。
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    stop = threading.Event()

    # 生成器对象在此创建（**不启动**）——真正的执行发生在 worker 线程里
    gen = executor.execute_stream(
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
        # **W2-02**：把 run / session 归属传下去（此前恒为 None → 成本统计恒为 0）
        role_id=payload.role_id,
        debug_prompt=payload.debug_prompt,
        trigger="api",
    )

    def drain() -> None:
        """在**单个线程 + 单个 Context** 内消费同步生成器（contextvar 全程有效）。"""
        try:
            for event in gen:
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except GeneratorExit:  # pragma: no cover - 客户端断开
            raise
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "content": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            # 关闭生成器 → 触发 run_executor 的 GeneratorExit 分支（标记 interrupted）
            try:
                gen.close()
            except Exception:  # noqa: BLE001
                pass
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    async def event_stream():
        # **关键**：整个 drain 在同一个 Context 里跑
        ctx = contextvars.copy_context()
        worker = asyncio.create_task(asyncio.to_thread(ctx.run, drain))
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            stop.set()
            worker.cancel()

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
        role_id=payload.role_id,   # P2-10
        debug_prompt=payload.debug_prompt,   # P4-06
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
        # 回显**实际执行**的模式（会话模式不可变时可能与请求不同）——
        # 避免响应声称 work、实际按 chat 跑。
        mode=result.get("mode") or payload.mode,
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
def agent_chat(
    req: AgentChatRequest,
    executor: RunExecutor = Depends(get_run_executor),
) -> AgentChatResponse:
    """WR 范式 Agent —— **已转调统一执行器**（P2-24）。

    此前本端点走遗留 ``app/services/agent/service.py``：那是**第二套**
    function-calling 循环（自述「不落账、不参与统一执行器」）→
    全仓存在两套主循环。

    现在统一走 ``run_executor``：调用后 **``runs`` 表有对应行**
    （可查、可回放），且全仓**只保留一套** function-calling 循环。

    响应字段从统一执行器的事件流装配：
    ``plan`` → ``plan`` 事件；``reflection_plan`` → ``reflection_plan`` 事件；
    ``memory`` → ``memory_item`` 事件；``answer`` → ``model_text`` 拼接。
    """
    plan: list = []
    reflection_plan: list | None = None
    memory: list = []
    answer_parts: list[str] = []
    error: str | None = None

    try:
        for ev in executor.execute_stream(
            req.query, mode="work", enable_reflection=req.reflection,
        ):
            kind = ev.get("type")
            if kind == "plan":
                plan = ev.get("actions") or []
            elif kind == "reflection_plan":
                reflection_plan = ev.get("actions") or []
            elif kind == "memory_item":
                memory.append({
                    "tool": ev.get("tool", ""),
                    "input": ev.get("input") or {},
                    "result": ev.get("result", ""),
                })
            elif kind == "model_text":
                answer_parts.append(ev.get("content") or "")
            elif kind == "error":
                error = ev.get("content")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("agent_chat 失败")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if error:
        raise HTTPException(status_code=500, detail=error)

    return AgentChatResponse(
        query=req.query,
        plan=plan,
        reflection_plan=reflection_plan,
        memory=memory,
        reasoning="",
        answer="".join(answer_parts),
    )

"""运行账本接口：详情 / 事件回放 / 实时事件流（DB tail SSE）。"""
import json
import time

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_run_executor, get_run_service
from app.schemas.common import Page
from app.schemas.run import RunEventPage, RunOut
from app.services.run_executor import RunExecutor
from app.services.run_service import TERMINAL_STATUSES, RunService

router = APIRouter(prefix="/runs", tags=["runs"])

STREAM_POLL_INTERVAL = 0.3
STREAM_MAX_SECONDS = 1800


@router.get("", response_model=Page[RunOut], summary="运行记录列表")
def list_runs(
    task_id: str | None = None,
    status: str | None = Query(
        default=None,
        description="按状态过滤（如 running / success / failed / interrupted）",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: RunService = Depends(get_run_service),
) -> Page[RunOut]:
    """运行记录列表。

    **不新增 `/runs/active`**：本文件先声明了 `GET /runs/{run_id}`，FastAPI 按声明顺序
    匹配，`/runs/active` 会被当作 run_id 捕获并返回 404（见 `../design/05` §3.4）。
    并行任务观察用 `GET /runs?status=running`。
    """
    items, total = service.list_runs(
        task_id=task_id, status=status, page=page, page_size=page_size
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{run_id}", response_model=RunOut, summary="运行详情")
def get_run(run_id: str, service: RunService = Depends(get_run_service)) -> RunOut:
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@router.get("/{run_id}/events", response_model=RunEventPage, summary="事件回放（分页）")
def list_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    service: RunService = Depends(get_run_service),
) -> RunEventPage:
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    items, last_seq, status = service.list_events(run_id, after_seq=after_seq, limit=limit)
    has_more = len(items) == limit
    return RunEventPage(items=items, last_seq=last_seq, status=status, has_more=has_more)  # type: ignore[arg-type]


@router.get("/{run_id}/stream", summary="运行事件流（DB tail SSE，支持断线续传）")
def stream_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    def event_stream():
        seq = after_seq
        deadline = time.monotonic() + STREAM_MAX_SECONDS
        while time.monotonic() < deadline:
            items, last_seq, status = service.list_events(run_id, after_seq=seq, limit=500)
            for item in items:
                payload = {"type": item.type, "seq": item.seq, **item.payload}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            seq = max(seq, last_seq)
            if status in TERMINAL_STATUSES and not items:
                yield f"data: {json.dumps({'type': 'done', 'status': status}, ensure_ascii=False)}\n\n"
                return
            time.sleep(STREAM_POLL_INTERVAL)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel", summary="中止运行中的任务")
def cancel_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
    executor: RunExecutor = Depends(get_run_executor),
) -> dict:
    """主动中止运行。

    与「客户端断开」不同，本端点**主动**置位取消标志：下一轮迭代起点即退出。
    正在执行的本地命令（阻塞式 ``subprocess.run``）不会被立即终止。
    """
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    executor.request_cancel(run_id)
    return {"ok": True, "run_id": run_id, "status": "interrupted"}


@router.post("/{run_id}/steer", summary="运行中介入：追加转向指令")
def steer_run(
    run_id: str,
    payload: dict = Body(default_factory=dict),
    service: RunService = Depends(get_run_service),
    executor: RunExecutor = Depends(get_run_executor),
) -> dict:
    """在运行中追加一条指令，让 Agent 调整方向（**不中止**本次运行）。

    指令会在**下一轮**迭代开始前并入上下文，因此能从下一个 ``round_input``
    事件中观察到。已知边界：若当前正在执行本地命令，需等该命令结束才生效。
    """
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    instruction = str(payload.get("instruction") or payload.get("text") or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="缺少 instruction")
    mode = str(payload.get("mode", "append")).strip()
    if mode not in ("append", "replace_plan"):
        raise HTTPException(status_code=422, detail="mode 必须是 append 或 replace_plan")
    accepted = executor.request_steer(run_id, instruction, mode=mode)
    return {
        "ok": accepted,
        "run_id": run_id,
        "mode": mode,
        "status": "queued" if accepted else "rejected",
        "note": "指令将在下一个工具边界注入；正在执行的命令结束后才生效",
    }

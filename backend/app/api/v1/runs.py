"""运行账本接口：详情 / 事件回放 / 实时事件流（DB tail SSE）。"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_run_service
from app.schemas.common import Page
from app.schemas.run import RunEventPage, RunOut
from app.services.run_service import TERMINAL_STATUSES, RunService

router = APIRouter(prefix="/runs", tags=["runs"])

STREAM_POLL_INTERVAL = 0.3
STREAM_MAX_SECONDS = 1800


@router.get("", response_model=Page[RunOut], summary="运行记录列表")
def list_runs(
    task_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: RunService = Depends(get_run_service),
) -> Page[RunOut]:
    items, total = service.list_runs(task_id=task_id, page=page, page_size=page_size)
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

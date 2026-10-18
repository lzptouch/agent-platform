"""定时任务接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_run_service, get_scheduler_service
from app.schemas.common import Page
from app.schemas.run import RunOut
from app.schemas.schedule import (
    CronValidateOut,
    CronValidateRequest,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
)
from app.services.run_service import RunService
from app.services.scheduler_service import SchedulerService

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[ScheduleOut], summary="任务列表")
def list_schedules(
    enabled: bool | None = None,
    service: SchedulerService = Depends(get_scheduler_service),
) -> list[ScheduleOut]:
    return service.list(enabled=enabled)


@router.post("", response_model=ScheduleOut, status_code=201, summary="创建任务")
def create_schedule(
    payload: ScheduleCreate,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduleOut:
    try:
        return service.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/validate", response_model=CronValidateOut, summary="cron 校验与未来触发预览")
def validate_cron(payload: CronValidateRequest) -> CronValidateOut:
    result = SchedulerService.validate_cron(payload.cron_expr, payload.timezone)
    return CronValidateOut(**result)


@router.get("/health", summary="调度器健康（租约/角色/job 数）")
def scheduler_health(service: SchedulerService = Depends(get_scheduler_service)) -> dict:
    return service.health()


@router.get("/{task_id}", response_model=ScheduleOut, summary="任务详情")
def get_schedule(task_id: str, service: SchedulerService = Depends(get_scheduler_service)) -> ScheduleOut:
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.put("/{task_id}", response_model=ScheduleOut, summary="更新任务（重建 job）")
def update_schedule(
    task_id: str,
    payload: ScheduleUpdate,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduleOut:
    try:
        task = service.update(task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.delete("/{task_id}", status_code=204, summary="删除任务（运行历史保留）")
def delete_schedule(task_id: str, service: SchedulerService = Depends(get_scheduler_service)) -> None:
    if not service.delete(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/{task_id}/toggle", response_model=ScheduleOut, summary="启停用任务")
def toggle_schedule(
    task_id: str,
    payload: ToggleRequest,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduleOut:
    try:
        ok = service.set_enabled(task_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = service.get(task_id)
    assert task is not None
    return task


@router.post("/{task_id}/run-now", summary="立即执行一次")
def run_now(
    task_id: str,
    wait_seconds: float = Query(default=0, ge=0, le=300),
    service: SchedulerService = Depends(get_scheduler_service),
) -> dict:
    try:
        return service.run_now(task_id, wait_seconds=wait_seconds)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None


@router.get("/{task_id}/runs", response_model=Page[RunOut], summary="运行历史（分页）")
def list_schedule_runs(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: SchedulerService = Depends(get_scheduler_service),
    run_service: RunService = Depends(get_run_service),
) -> Page[RunOut]:
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    items, total = run_service.list_runs(task_id=task_id, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)

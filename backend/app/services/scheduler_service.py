"""SchedulerService —— 定时任务调度（APScheduler + DB 唯一真相）。

设计要点：
- **表为唯一真相**：任务定义在 ``scheduled_tasks``，启动时重建 job，不使用 jobstore 双写；
- **幂等**：槽位 ``scheduled_for`` 确定性计算（cron 按分钟截断，interval 以 created_at 为锚），
  由 ``UNIQUE(task_id, scheduled_for)`` 兜底，重启 / 补跑 / 并发不会重复执行；
- **租约**：``system_locks`` DB 租约，多进程只有一个 primary 持锁调度；
- **失败退避**：连续失败 ≥3 次指数退避；每日运行上限；全局并发信号量；
- **安全**：work 任务必须 allow_unattended_tools；execute_bash 需二次开关。
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.base import db_session
from app.db.models import RunRow, ScheduledTaskRow, SystemLockRow, utc_now
from app.schemas.schedule import ScheduleOut
from app.services.run_service import TERMINAL_STATUSES

if False:  # TYPE_CHECKING
    from app.services.run_executor import RunExecutor

logger = logging.getLogger(__name__)

LEASE_NAME = "scheduler"
MISFIRE_GRACE_SECONDS = 300
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
BACKOFF_THRESHOLD = 3


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _cron_desc(expr: str) -> str:
    parts = expr.split()
    if len(parts) != 5:
        return expr
    minute, hour, day, month, weekday = parts
    if expr.startswith("*/") and hour == "*" and day == "*" and month == "*" and weekday == "*":
        return f"每 {minute[2:]} 分钟"
    if minute != "*" and hour != "*" and day == "*" and month == "*" and weekday == "*":
        return f"每天 {hour.zfill(2)}:{minute.zfill(2)}"
    if minute != "*" and hour != "*" and day == "*" and month == "*" and weekday != "*":
        return f"每周 {weekday} {hour.zfill(2)}:{minute.zfill(2)}"
    return expr


def task_to_out(row: ScheduledTaskRow) -> ScheduleOut:
    enable = json.loads(row.enable_json or "{}")
    if row.schedule_kind == "cron":
        schedule_text = _cron_desc(row.cron_expr or "")
        suffix = f"（{row.timezone}）"
    else:
        sec = row.interval_seconds or 0
        schedule_text = f"每 {sec // 60} 分钟" if sec % 60 == 0 else f"每 {sec} 秒"
        suffix = ""
    health = "degraded" if row.consecutive_failures >= 5 else ("warning" if row.consecutive_failures >= 1 else "ok")
    return ScheduleOut(
        id=row.id,
        name=row.name,
        prompt=row.prompt,
        mode=row.mode,  # type: ignore[arg-type]
        plan_first=bool(row.plan_first),
        team_id=row.team_id,
        skills=json.loads(row.skills_json or "[]"),
        enable_mcp=bool(enable.get("mcp")),
        mcp_servers=enable.get("mcp_servers", []),
        enable_rag=bool(enable.get("rag")),
        enable_web_research=bool(enable.get("web")),
        enable_reflection=bool(enable.get("reflection")),
        schedule_kind=row.schedule_kind,  # type: ignore[arg-type]
        cron_expr=row.cron_expr,
        interval_seconds=row.interval_seconds,
        timezone=row.timezone,
        enabled=bool(row.enabled),
        allow_unattended_tools=bool(row.allow_unattended_tools),
        allow_dangerous_tools=bool(row.allow_dangerous_tools),
        daily_run_limit=row.daily_run_limit,
        schedule_text=schedule_text + suffix,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_status=row.last_status,
        last_error=row.last_error,
        run_count=row.run_count,
        consecutive_failures=row.consecutive_failures,
        health=health,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SchedulerService:
    def __init__(self, run_executor: RunExecutor | None = None) -> None:
        self.run_executor = run_executor
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.scheduler: BackgroundScheduler | None = None
        self.role = "standby"
        self._renew_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._renew_failures = 0

    # ------------------------------------------------------------------ #
    # 租约
    # ------------------------------------------------------------------ #
    def _acquire_lease(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=settings.schedule_lease_ttl)).isoformat()
        with db_session() as db:
            row = db.get(SystemLockRow, LEASE_NAME)
            if row is None:
                db.add(SystemLockRow(
                    name=LEASE_NAME, owner=self.owner,
                    expires_at=expires, renewed_at=now.isoformat(),
                ))
                return True
            if row.owner == self.owner or (row.expires_at < now.isoformat()):
                row.owner = self.owner
                row.expires_at = expires
                row.renewed_at = now.isoformat()
                return True
            return False

    def _renew_lease(self) -> bool:
        now = datetime.now(timezone.utc)
        with db_session() as db:
            row = db.get(SystemLockRow, LEASE_NAME)
            if row is None or row.owner != self.owner:
                return False
            row.expires_at = (now + timedelta(seconds=settings.schedule_lease_ttl)).isoformat()
            row.renewed_at = now.isoformat()
            return True

    def _release_lease(self) -> None:
        with db_session() as db:
            row = db.get(SystemLockRow, LEASE_NAME)
            if row and row.owner == self.owner:
                db.delete(row)

    def _renew_loop(self) -> None:
        while not self._stop_event.wait(settings.schedule_lease_renew):
            try:
                if self._renew_lease():
                    self._renew_failures = 0
                else:
                    self._renew_failures += 1
            except Exception:  # noqa: BLE001
                logger.exception("租约续约失败")
                self._renew_failures += 1
            if self._renew_failures >= 3:
                logger.error("租约丢失，停止调度（分裂脑保护）")
                self._stop_scheduler_only()
                return

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("调度器已禁用（SCHEDULER_ENABLED=false），以只读模式运行")
            return
        if self.scheduler is not None:
            return
        if not self._acquire_lease():
            logger.warning("未获得调度租约，本实例以 standby 运行（仅提供 API）")
            self.role = "standby"
            return

        self.role = "primary"
        self.scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.tz))
        self.scheduler.start()
        self.recover()
        self.sync_all_jobs()
        # 每日清理
        self.scheduler.add_job(
            self.cleanup_runs, CronTrigger(hour=3, minute=30, timezone=ZoneInfo(settings.tz)),
            id="__cleanup__", replace_existing=True,
        )
        self._stop_event.clear()
        self._renew_thread = threading.Thread(target=self._renew_loop, name="scheduler-lease", daemon=True)
        self._renew_thread.start()
        logger.info("调度器已启动（primary, owner=%s）", self.owner)

    def _stop_scheduler_only(self) -> None:
        if self.scheduler is not None:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
            self.scheduler = None
            self.role = "standby"

    def shutdown(self, wait: bool = False) -> None:
        self._stop_event.set()
        self._stop_scheduler_only()
        self._release_lease()
        logger.info("调度器已关闭")

    # ------------------------------------------------------------------ #
    # 任务同步（表 → job）
    # ------------------------------------------------------------------ #
    def _build_trigger(self, row: ScheduledTaskRow):
        tz = ZoneInfo(row.timezone)
        if row.schedule_kind == "cron":
            return CronTrigger.from_crontab(row.cron_expr, timezone=tz)
        return IntervalTrigger(seconds=row.interval_seconds, timezone=tz)

    def _job_kwargs(self) -> dict:
        return {
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": MISFIRE_GRACE_SECONDS,
        }

    def sync_task(self, task_id: str) -> None:
        if self.scheduler is None:
            return
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None or not row.enabled:
                self.scheduler.remove_job(task_id) if self.scheduler.get_job(task_id) else None
                return
            self.scheduler.add_job(
                self._fire, self._build_trigger(row),
                id=task_id, args=[task_id], replace_existing=True,
                **self._job_kwargs(),
            )
            job = self.scheduler.get_job(task_id)
            if job and job.next_run_time:
                row.next_run_at = job.next_run_time.astimezone(timezone.utc).isoformat()

    def remove_task(self, task_id: str) -> None:
        if self.scheduler is not None and self.scheduler.get_job(task_id):
            self.scheduler.remove_job(task_id)

    def sync_all_jobs(self) -> int:
        with db_session() as db:
            ids = db.scalars(
                select(ScheduledTaskRow.id).where(ScheduledTaskRow.enabled == 1)
            ).all()
        for task_id in ids:
            try:
                self.sync_task(task_id)
            except Exception:  # noqa: BLE001
                logger.exception("重建 job 失败: %s", task_id)
        return len(ids)

    def recover(self) -> int:
        from app.services.run_service import RunService

        return RunService().recover_interrupted()

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(self, data) -> ScheduleOut:
        with db_session() as db:
            total = db.scalar(select(func.count()).select_from(ScheduledTaskRow)) or 0
            if total >= settings.schedule_task_soft_limit:
                raise ValueError(f"任务数量已达上限 {settings.schedule_task_soft_limit}")
            row = ScheduledTaskRow(
                name=data.name.strip(),
                prompt=data.prompt,
                mode=data.mode,
                plan_first=1 if data.plan_first else 0,
                team_id=data.team_id,
                skills_json=json.dumps(data.skills or [], ensure_ascii=False),
                enable_json=json.dumps({
                    "mcp": data.enable_mcp, "mcp_servers": data.mcp_servers,
                    "rag": data.enable_rag, "web": data.enable_web_research,
                    "reflection": data.enable_reflection,
                }, ensure_ascii=False),
                schedule_kind=data.schedule_kind,
                cron_expr=data.cron_expr,
                interval_seconds=data.interval_seconds,
                timezone=data.timezone,
                enabled=1 if data.enabled else 0,
                allow_unattended_tools=1 if data.allow_unattended_tools else 0,
                allow_dangerous_tools=1 if data.allow_dangerous_tools else 0,
                daily_run_limit=data.daily_run_limit,
            )
            db.add(row)
            db.flush()
            task_id = row.id
        self.sync_task(task_id)
        return self.get(task_id)  # type: ignore[return-value]

    def get(self, task_id: str) -> ScheduleOut | None:
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            return task_to_out(row) if row else None

    def list(self, enabled: bool | None = None) -> list[ScheduleOut]:
        with db_session() as db:
            stmt = select(ScheduledTaskRow).order_by(ScheduledTaskRow.created_at.desc())
            if enabled is not None:
                stmt = stmt.where(ScheduledTaskRow.enabled == (1 if enabled else 0))
            return [task_to_out(r) for r in db.scalars(stmt).all()]

    def update(self, task_id: str, data) -> ScheduleOut | None:
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None:
                return None
            for key in ("name", "prompt", "timezone", "cron_expr", "interval_seconds"):
                val = getattr(data, key, None)
                if val is not None:
                    setattr(row, key, val)
            if data.mode is not None:
                row.mode = data.mode
            if data.plan_first is not None:
                row.plan_first = 1 if data.plan_first else 0
            if data.team_id is not None:
                row.team_id = data.team_id
            if data.skills is not None:
                row.skills_json = json.dumps(data.skills, ensure_ascii=False)
            if data.daily_run_limit is not None:
                row.daily_run_limit = data.daily_run_limit
            if data.allow_unattended_tools is not None:
                row.allow_unattended_tools = 1 if data.allow_unattended_tools else 0
            if data.allow_dangerous_tools is not None:
                row.allow_dangerous_tools = 1 if data.allow_dangerous_tools else 0
            enable = json.loads(row.enable_json or "{}")
            for key, field in (("mcp", "enable_mcp"), ("rag", "enable_rag"),
                               ("web", "enable_web_research"), ("reflection", "enable_reflection")):
                val = getattr(data, field, None)
                if val is not None:
                    enable[key] = val
            if data.mcp_servers is not None:
                enable["mcp_servers"] = data.mcp_servers
            row.enable_json = json.dumps(enable, ensure_ascii=False)
            # cron/interval 二选一：明确给定一个时清掉另一个
            if data.cron_expr is not None:
                row.schedule_kind, row.interval_seconds = "cron", None
            elif data.interval_seconds is not None:
                row.schedule_kind, row.cron_expr = "interval", None
            row.updated_at = utc_now()
            # 安全校验（与创建一致）
            if row.mode == "work" and row.enabled and not row.allow_unattended_tools:
                raise ValueError("工作模式的启用任务需显式确认 allow_unattended_tools=true")
            if row.mode == "chat" and row.plan_first:
                raise ValueError("对话模式不支持 plan_first")
        self.sync_task(task_id)
        return self.get(task_id)

    def delete(self, task_id: str) -> bool:
        self.remove_task(task_id)
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None:
                return False
            db.execute(
                RunRow.__table__.update().where(RunRow.task_id == task_id).values(task_id=None)
            )
            db.delete(row)
            return True

    def set_enabled(self, task_id: str, enabled: bool) -> bool:
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None:
                return False
            if enabled and row.mode == "work" and not row.allow_unattended_tools:
                raise ValueError("启用工作模式任务需先确认 allow_unattended_tools")
            row.enabled = 1 if enabled else 0
            row.updated_at = utc_now()
        self.sync_task(task_id)
        return True

    # ------------------------------------------------------------------ #
    # 触发执行
    # ------------------------------------------------------------------ #
    def _compute_slot(self, row: ScheduledTaskRow) -> str:
        """确定性槽位：重启/补跑/并发计算结果一致。"""
        now = datetime.now(timezone.utc)
        if row.schedule_kind == "cron":
            return now.replace(second=0, microsecond=0).isoformat()
        created = _parse_iso(row.created_at) or now
        interval = row.interval_seconds or 60
        idx = int((now - created).total_seconds() // interval)
        return (created + timedelta(seconds=idx * interval)).isoformat()

    def _build_exec_meta(self, row: ScheduledTaskRow) -> dict:
        enable = json.loads(row.enable_json or "{}")
        return {
            "prompt": row.prompt,
            "mode": row.mode,
            "model": settings.default_model,
            "team_id": row.team_id,
            "skills": json.loads(row.skills_json or "[]") or None,
            "enable_mcp": bool(enable.get("mcp")),
            "mcp_servers": enable.get("mcp_servers", []),
            "enable_rag": bool(enable.get("rag")),
            "enable_web_research": bool(enable.get("web")),
            "enable_reflection": bool(enable.get("reflection")),
            "plan_first": bool(row.plan_first),
        }

    def _fire(self, task_id: str) -> None:
        from app.services.run_service import RunService

        run_service = RunService()
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None or not row.enabled:
                return
            task = task_to_out(row)

        slot = self._compute_slot(row)

        # 退避
        backoff = _parse_iso(row.backoff_until)
        if backoff and backoff > datetime.now(timezone.utc):
            run = run_service.create_run(
                trigger="schedule", task_id=task_id, scheduled_for=slot, meta={"reason": "backoff"},
            )
            if run:
                run_service.finish(run.id, "skipped", error="失败退避中")
            self._mark_task(task_id, last_status="skipped")
            return

        # 每日配额
        if run_service.count_today_runs(task_id) >= task.daily_run_limit:
            run = run_service.create_run(
                trigger="schedule", task_id=task_id, scheduled_for=slot, meta={"reason": "daily_limit"},
            )
            if run:
                run_service.finish(run.id, "skipped", error="达到每日运行上限")
            self._mark_task(task_id, last_status="skipped")
            return

        # 幂等闸门：预创建 run（同槽位唯一冲突即跳过）
        run = run_service.create_run(
            trigger="schedule", task_id=task_id, scheduled_for=slot,
            status="queued", meta=self._build_exec_meta(row),
        )
        if run is None:
            logger.info("槽位已执行过，跳过: task=%s slot=%s", task_id, slot)
            return

        if self.run_executor is None:
            run_service.finish(run.id, "failed", error="执行器未初始化")
            self._mark_task(task_id, last_status="failed", error="执行器未初始化", increment=True)
            return

        meta = self._build_exec_meta(row)
        result = self.run_executor.execute_sync(
            task.prompt,
            mode=task.mode,
            team_id=task.team_id,
            skills=meta["skills"],
            enable_mcp=meta["enable_mcp"],
            mcp_servers=meta["mcp_servers"],
            enable_rag=meta["enable_rag"],
            enable_web_research=meta["enable_web_research"],
            enable_reflection=meta["enable_reflection"] and task.mode == "work",
            plan_first=bool(task.plan_first),
            trigger="schedule",
            task_id=task_id,
            scheduled_for=slot,
            run_id=run.id,
        )

        if result.get("skipped"):
            run_service.finish(run.id, "skipped", error=result.get("error", "busy"))
            self._mark_task(task_id, last_status="skipped")
            return

        # plan_first 定时任务：自动批准并恢复执行（无人值守）
        current = run_service.get_run(run.id)
        if current and current.status == "awaiting_approval" and task.plan_first:
            approved = run_service.approve_plan(run.id)
            if approved:
                meta["plan_auto_approved"] = True
                run_service.update_meta(run.id, meta)
                self.run_executor.resume_after_approval(run.id)
                self._mark_task(task_id, last_status="running")
                return

        error = result.get("error")
        self._mark_task(
            task_id,
            last_status="failed" if error else "success",
            error=error,
            increment=True,
        )

    def _mark_task(self, task_id: str, *, last_status: str, error: str | None = None,
                   increment: bool = False) -> None:
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            row.last_run_at = utc_now()
            row.last_status = last_status
            if increment:
                row.run_count += 1
            if last_status == "failed":
                row.consecutive_failures += 1
                row.last_error = (error or "")[:500]
                if row.consecutive_failures >= BACKOFF_THRESHOLD:
                    delay = min(
                        BACKOFF_BASE_SECONDS * (2 ** (row.consecutive_failures - BACKOFF_THRESHOLD)),
                        BACKOFF_MAX_SECONDS,
                    )
                    row.backoff_until = (
                        datetime.now(timezone.utc) + timedelta(seconds=delay)
                    ).isoformat()
            elif last_status == "success":
                row.consecutive_failures = 0
                row.backoff_until = None
                row.last_error = None
            elif last_status == "skipped":
                row.last_error = (error or "")[:500] or row.last_error
        self.sync_task(task_id)

    # ------------------------------------------------------------------ #
    # 立即执行
    # ------------------------------------------------------------------ #
    def run_now(self, task_id: str, wait_seconds: float = 0) -> dict:
        from app.services.run_service import RunService

        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None:
                raise KeyError(f"任务不存在: {task_id}")
            task = task_to_out(row)
            enable = json.loads(row.enable_json or "{}")
            skills = json.loads(row.skills_json or "[]") or None

        run_service = RunService()
        run = run_service.create_run(
            trigger="manual", task_id=task_id, scheduled_for=None,
            status="queued", meta=self._build_exec_meta(row),
        )
        if run is None:
            raise RuntimeError("创建运行记录失败")

        def _execute() -> None:
            if self.run_executor is None:
                run_service.finish(run.id, "failed", error="执行器未初始化")
                return
            meta = self._build_exec_meta(row)
            result = self.run_executor.execute_sync(
                task.prompt,
                mode=task.mode,
                team_id=task.team_id,
                skills=skills,
                enable_mcp=bool(enable.get("mcp")),
                mcp_servers=enable.get("mcp_servers", []),
                enable_rag=bool(enable.get("rag")),
                enable_web_research=bool(enable.get("web")),
                enable_reflection=bool(enable.get("reflection")) and task.mode == "work",
                plan_first=bool(task.plan_first),
                trigger="manual",
                task_id=task_id,
                run_id=run.id,
            )
            if result.get("skipped"):
                run_service.finish(run.id, "skipped", error=result.get("error", "busy"))
                self._mark_task(task_id, last_status="skipped")
                return
            current = run_service.get_run(run.id)
            if current and current.status == "awaiting_approval" and task.plan_first:
                approved = run_service.approve_plan(run.id)
                if approved:
                    self.run_executor.resume_after_approval(run.id)
                    self._mark_task(task_id, last_status="running")
                    return
            if current and current.status in TERMINAL_STATUSES:
                self._mark_task(
                    task_id,
                    last_status=current.status,
                    error=current.error,
                    increment=True,
                )

        thread = threading.Thread(target=_execute, name=f"run-now-{run.id[:8]}", daemon=True)
        thread.start()

        if wait_seconds > 0:
            deadline = time.time() + min(wait_seconds, 300)
            while time.time() < deadline:
                current = run_service.get_run(run.id)
                if current and current.status in TERMINAL_STATUSES:
                    break
                time.sleep(0.5)

        out = run_service.get_run(run.id)
        return {"run_id": run.id, "status": out.status if out else "unknown"}

    # ------------------------------------------------------------------ #
    # 清理与健康
    # ------------------------------------------------------------------ #
    def cleanup_runs(self) -> int:
        from app.services.run_service import RunService

        return RunService().cleanup()

    def health(self) -> dict:
        jobs = len(self.scheduler.get_jobs()) if self.scheduler is not None else 0
        return {
            "role": self.role,
            "owner": self.owner if self.role == "primary" else None,
            "jobs": jobs,
            "enabled": settings.scheduler_enabled,
        }

    @staticmethod
    def validate_cron(expr: str, timezone_str: str) -> dict:
        try:
            trigger = CronTrigger.from_crontab(expr.strip(), timezone=ZoneInfo(timezone_str))
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc), "next_runs": []}
        next_runs = []
        t = datetime.now(ZoneInfo(timezone_str))
        for _ in range(3):
            t = trigger.get_next_fire_time(None, t)
            if t is None:
                break
            next_runs.append(t.astimezone(timezone.utc).isoformat())
            t = t + timedelta(seconds=1)  # get_next_fire_time 为闭区间，需前移避免重复
        return {"valid": True, "error": None, "next_runs": next_runs}

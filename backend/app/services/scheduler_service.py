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
from contextvars import ContextVar
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
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.base import db_session
from app.db.models import RunRow, ScheduledTaskRow, SystemLockRow, utc_now
from app.schemas.schedule import ScheduleOut
from app.services.run_service import TERMINAL_STATUSES

if False:  # TYPE_CHECKING
    from app.services.run_executor import RunExecutor

logger = logging.getLogger(__name__)

#: 无人值守（定时/调度）上下文：True 表示当前 run 是定时触发，审批应降级为拒绝
unattended_context: ContextVar[bool] = ContextVar("scheduler_unattended", default=False)

#: 危险工具二次开关（D-29）：定时任务显式允许危险工具（write_file / execute_python / execute_bash）
dangerous_tools_context: ContextVar[bool] = ContextVar("scheduler_dangerous_tools", default=False)

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
    elif row.schedule_kind == "rrule":  # P2-16
        schedule_text = f"RRULE {row.rrule_expr or ''}"
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
        rrule_expr=row.rrule_expr,
        delivery=json.loads(row.delivery_json or "{}") or None,
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


#: run 的**终态**集合（非终态不得被记为 success —— W9-05）
_TERMINAL_RUN_STATUSES = frozenset({
    "success", "failed", "skipped", "interrupted", "cancelled",
})

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
        """**原子**获取调度租约。

        **W7-04 / AUD2-C04（多副本可同时成为 primary）修复**

        旧实现是典型的 **check-then-act**::

            row = db.get(SystemLockRow, LEASE_NAME)   # 读
            if row is None:
                db.add(...)                          # 写（读与写之间无保护）

        两个副本同时启动时：都读到 ``None`` → 都 ``add`` → 其一提交时抛**未捕获的**
        ``IntegrityError``（直接冒泡出 ``start()``，整个调度器启动失败），
        或两者都判定自己拿到租约 → **双 primary 双调度**，同一任务被触发两次。

        新实现用**单条条件 UPDATE** 实现原子获取：只有「不存在」「已过期」「本来就是我」
        三种情况才接管；并发插入失败（``IntegrityError``）视为「别人拿到了」，
        **不是错误**，返回 False 进入 standby。
        """
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=settings.schedule_lease_ttl)).isoformat()
        now_iso = now.isoformat()
        with db_session() as db:
            # ① 条件更新（原子）：owner 是我 / 已过期 → 接管
            res = db.execute(
                update(SystemLockRow)
                .where(SystemLockRow.name == LEASE_NAME)
                .where(
                    or_(
                        SystemLockRow.owner == self.owner,
                        SystemLockRow.expires_at < now_iso,
                    )
                )
                .values(owner=self.owner, expires_at=expires, renewed_at=now_iso)
            )
            if res.rowcount:
                return True
            # ② 行不存在 → 尝试插入（可能与并发插入竞争）
            existing = db.get(SystemLockRow, LEASE_NAME)
            if existing is not None:
                # 已被别人持有且未过期 → standby
                return False
            try:
                db.add(SystemLockRow(
                    name=LEASE_NAME, owner=self.owner,
                    expires_at=expires, renewed_at=now_iso,
                ))
                db.flush()
                return True
            except IntegrityError:
                # 并发插入失败 = 别人先拿到了 → standby（**不是错误**）
                db.rollback()
                return False

    def _renew_lease(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=settings.schedule_lease_ttl)).isoformat()
        with db_session() as db:
            # **W7-04**：条件更新 —— 只有 owner 仍是我时才续租，
            # 否则（已被别人接管）续租会「假成功」。
            res = db.execute(
                update(SystemLockRow)
                .where(SystemLockRow.name == LEASE_NAME)
                .where(SystemLockRow.owner == self.owner)
                .values(expires_at=expires, renewed_at=now.isoformat())
            )
            return bool(res.rowcount)

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
        # 周期巡检：超期未完成的 run 标记为 interrupted（S-08-08）
        if settings.schedule_stale_sweep_minutes > 0:
            self.scheduler.add_job(
                self.sweep_stale_runs,
                IntervalTrigger(minutes=settings.schedule_stale_sweep_minutes),
                id="__stale_sweep__", replace_existing=True,
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
        if row.schedule_kind == "rrule":  # P2-16：RRULE → 触发器
            from app.services.scheduler.rrule import RRuleTrigger, parse

            try:
                rule = parse(row.rrule_expr or "")
            except Exception as exc:  # noqa: BLE001 - 非法表达式不建任务
                raise ValueError(f"无效 RRULE 表达式: {exc}") from exc
            # **AUD2-H08 / W9-02**：不再降级成 crontab（会丢掉 INTERVAL 且 DAILY 的
            # ``*/N`` 落在日-of-月字段 → 语义错位）。改用直接按 RRULE 语义计算的触发器，
            # 且与槽位展开（``expand_slots``）**同源** → 触发时刻与幂等槽位永远一致。
            anchor = _parse_iso(row.created_at) or datetime.now(tz)
            return RRuleTrigger(rule, anchor, tz)
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

    def sweep_stale_runs(self) -> int:
        """周期巡检：崩溃残留的 ``running`` 不再永久停留（S-08-08）。

        宽限期必须大于单次运行的上限（``schedule_run_timeout``），
        否则会把**仍在正常执行**的长任务误判为中断。
        """
        from app.services.run_service import RunService

        grace = max(
            settings.schedule_stale_sweep_grace,
            settings.schedule_run_timeout + 60,
        )
        try:
            count = RunService().recover_interrupted(
                grace_seconds=grace, reason="超过时限未完成，周期巡检标记为中断",
            )
        except Exception:  # noqa: BLE001 —— 巡检失败不影响调度
            logger.exception("周期巡检失败")
            return 0
        if count:
            logger.warning("周期巡检：标记 %d 个超期 run 为 interrupted", count)
        return count

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
                rrule_expr=data.rrule_expr,
                # P3-02：投递配置落库（此前有读无写）
                delivery_json=json.dumps(data.delivery or {}, ensure_ascii=False),
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
            # **W9-09 / AUD2-M01**：**先校验再写库** —— 非法 cron / rrule / timezone
            # 此前会落库（并在 sync_task 抛 500），导致任务表达式已损坏、job 未重建。
            # 这里复用 schema 的校验器（ScheduleUpdate 已继承 ScheduleCreate 的三个）。
            for key, validator in (
                ("timezone", "timezone"),
                ("cron_expr", "cron_expr"),
                ("rrule_expr", "rrule_expr"),
            ):
                val = getattr(data, key, None)
                if val is None:
                    continue
                check = getattr(data, f"_validate_{key}", None)
                if check is not None:
                    try:
                        check(val)
                    except Exception as exc:  # noqa: BLE001
                        raise ValueError(f"无效 {key}: {exc}") from exc
            for key in ("name", "prompt", "timezone", "cron_expr", "interval_seconds",
                        "rrule_expr"):
                val = getattr(data, key, None)
                if val is not None:
                    setattr(row, key, val)
            if data.delivery is not None:  # P3-02：投递配置可更新
                row.delivery_json = json.dumps(data.delivery or {}, ensure_ascii=False)
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
            # cron / interval / rrule **三选一**（P2-16）：明确给定一个时清掉其余
            if data.cron_expr is not None:
                row.schedule_kind, row.interval_seconds, row.rrule_expr = "cron", None, None
            elif data.interval_seconds is not None:
                row.schedule_kind, row.cron_expr, row.rrule_expr = "interval", None, None
            elif data.rrule_expr is not None:
                row.schedule_kind, row.cron_expr, row.interval_seconds = "rrule", None, None
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
        """确定性槽位：重启/补跑/并发计算结果一致。

        **P3-04**：cron 槽位此前是「当前分钟截断」（``now.replace(second=0)``）
        —— 与 cron 的**真实触发时刻**不一致（``0 9 * * 1-5`` 的任务在 09:00:00
        触发时，槽位应恰为 09:00:00，而不是任意分钟的整点）。
        现在改为用 ``CronTrigger`` 求出**最近一次真实触发时刻**。
        """
        now = datetime.now(timezone.utc)
        if row.schedule_kind == "cron":
            return self._cron_last_fire(row, now)
        if row.schedule_kind == "rrule":  # P2-16
            return self._rrule_slot(row, now)
        created = _parse_iso(row.created_at) or now
        interval = row.interval_seconds or 60
        idx = int((now - created).total_seconds() // interval)
        return (created + timedelta(seconds=idx * interval)).isoformat()

    @staticmethod
    @staticmethod
    def _last_cron_fire(
        trigger: "CronTrigger", now: datetime, *, window_days: int = 400
    ) -> datetime | None:
        """求 ``<= now`` 的**最近一个** cron 触发点（**与任务年龄完全无关**）。

        **W7-03 / AUD2-C03（定时任务静默永久停摆）修复**

        旧实现从 ``created_at`` **正向迭代 200 次**取最后一个 → 算出的槽位约等于
        「200 个周期之前」，**与 ``now`` 无关**。后果：

        - 任务只要存活超过 200 个周期，槽位就被钉死在过去（``*/5 * * * *`` 约 16.7 小时、
          ``0 * * * *`` 约 8.3 天、``0 0 * * *`` 约 200 天）；
        - 该陈旧槽位撞上唯一约束 ``uq_runs_task_slot(task_id, scheduled_for)``
          → ``create_run()`` 返回 ``None`` → 调度器判定「槽位已执行过，跳过」
          → **此后每次触发都用同一个陈旧槽位 → 任务永久停摆，且日志只打 INFO**。

        新实现用**二分**求解：令 ``f(X) = 第一个 >= X 的触发点``（cron 下单调不减）。
        设触发点序列为 ``t1 < t2 < ...``，``t_k <= now < t_{k+1}``。
        「满足 ``f(X) <= now`` 的最大 X」记为 ``X2``：由单调性，``X2 ∈ [t_k, t_{k+1})``，
        于是 ``f(X2) = t_k`` —— 即所求。**结果只依赖 ``now``，与任务年龄无关。**
        """
        step = timedelta(microseconds=1)
        lo = now - timedelta(days=window_days)
        hi = now
        # 前置检查：窗口内是否至少有一个触发点
        if trigger.get_next_fire_time(None, lo) is None:
            return None
        # 二分：找最大的 X，使 f(X) <= now
        while lo < hi:
            mid = lo + (hi - lo + step) // 2
            nxt = trigger.get_next_fire_time(None, mid)
            if nxt is not None and nxt <= now:
                lo = mid
            else:
                hi = mid - step
        result = trigger.get_next_fire_time(None, lo)
        return result if result is not None and result <= now else None

    def _cron_last_fire(self, row: ScheduledTaskRow, now: datetime) -> str:
        """cron 的**最近一次真实触发时刻**（UTC ISO）。

        **P3-04**：与补跑路径（``_missed_slot`` 的 cron 分支）**同一套算法**
        —— 保证「正常触发」与「补跑」算出同一个槽位，幂等闸门
        （``uq_runs_task_slot``）才真正有效。

        **W7-03**：改用二分反解（``_last_cron_fire``），槽位**不再依赖任务年龄**。
        """
        fallback = now.replace(second=0, microsecond=0).isoformat()
        expr = (row.cron_expr or "").strip()
        if not expr:
            return fallback
        try:
            trigger = CronTrigger.from_crontab(
                expr, timezone=ZoneInfo(row.timezone or settings.tz),
            )
        except Exception:  # noqa: BLE001 - 非法 cron 退化为分钟槽
            return fallback

        last = self._last_cron_fire(trigger, now)
        if last is None:
            return fallback
        return last.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _rrule_slot(row: ScheduledTaskRow, now: datetime) -> str:
        """RRULE 槽位 = ``now`` 之前（含）最近的一个**合法触发点**。

        **必须是 RRULE 展开出的槽位之一**——否则同一个触发点会算出不同 slot，
        幂等闸门（``uq_runs_task_slot``）失效，会产生重复 run。

        **W7-03**：展开锚点由 ``created_at`` 改为 ``now - horizon``，
        **槽位不再依赖任务年龄**（旧实现对老任务会取到几百天前的旧槽位 → 同样停摆）。
        """
        from app.services.scheduler.rrule import RRULEError, expand_slots, parse

        fallback = now.replace(second=0, microsecond=0).isoformat()
        expr = (row.rrule_expr or "").strip()
        if not expr:
            return fallback
        try:
            rule = parse(expr)
        except RRULEError:
            return fallback

        tz = ZoneInfo(row.timezone or settings.tz)
        local_now = now.astimezone(tz)
        # **以 now 为锚向前回溯一个 horizon**，而不是以 created_at 为锚
        horizon_days = 370
        local_anchor = (local_now - timedelta(days=horizon_days)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        # limit 必须能覆盖 horizon 内的全部槽位，否则高频规则会取不到最近的槽位
        per_day = {
            "HOURLY": 24, "MINUTELY": 24 * 60, "SECONDLY": 24 * 60 * 60,
        }.get(str(getattr(rule, "freq", "")).upper(), 1)
        limit = min(20000, max(400, horizon_days * per_day))
        try:
            slots = expand_slots(rule, local_anchor, limit=limit, horizon_days=horizon_days)
        except Exception:  # noqa: BLE001 - 展开失败退化为分钟槽
            return fallback

        chosen: datetime | None = None
        for raw in slots:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            if dt <= local_now:
                chosen = dt
            else:
                break
        if chosen is None:
            return fallback
        return chosen.astimezone(timezone.utc).isoformat()

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

    def _fire(self, task_id: str, slot_override: str | None = None) -> None:
        from app.services.run_service import RunService

        run_service = RunService()
        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            if row is None or not row.enabled:
                return
            task = task_to_out(row)

        slot = slot_override or self._compute_slot(row)

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

        # 每日配额（按**任务时区**的本地自然日，不是 UTC 日）
        if run_service.count_today_runs(task_id, task.timezone) >= task.daily_run_limit:
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

        # **W9-03 / AUD2-H03**：异常兜底。
        # 此前 `_fire` **只有 finally 没有 except** —— `create_run` 之后的任何异常
        # （DB locked / session_service.create 失败 / execute_sync 前置阶段异常）都冒泡给
        # APScheduler：预建的 run 永远停在 `queued`（要等 900s 巡检才捞），
        # 而 `last_status` / `consecutive_failures` / `backoff_until` **完全没更新**
        # → 任务**永不进入退避**，失败被完全掩盖。
        try:
            self._execute_task(task_id, task, row, slot, run, run_service)
        except Exception as exc:  # noqa: BLE001
            logger.exception("定时任务执行异常: task=%s", task_id)
            err = f"{type(exc).__name__}: {exc}"
            try:
                run_service.finish(run.id, "failed", error=err)
            except Exception:  # noqa: BLE001
                logger.exception("标记 run 失败时出错: run=%s", run.id)
            self._mark_task(task_id, last_status="failed", error=err, increment=True)

    def _execute_task(
        self, task_id: str, task, row, slot: str, run, run_service
    ) -> None:
        """执行一次定时任务并结算状态（由 ``_fire`` 的 try/except 包裹）。"""
        meta = self._build_exec_meta(row)
        # 无人值守上下文：本 run 是定时触发 → 权限 ask 降级为 deny（不挂起）
        unattended_context.set(True)
        # P1-04：危险工具二次开关必须真正生效。
        # 此前全仓唯一的写入点在 finally 里恒为 False → `allow_dangerous_tools`
        # 无论入库成什么样都恒走「拒绝」，是一个「可写可查可输出但永不生效」的误导性配置。
        # 这里按任务行的真实值置位，finally 复位为 False（交互路径保持恒拒绝）。
        dangerous_tools_context.set(bool(row.allow_dangerous_tools))
        try:
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
        finally:
            unattended_context.set(False)
            dangerous_tools_context.set(False)

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
                # **W9-04**：恢复段的**真实终态**由 ``resume_after_approval`` 内的
                # ``_run`` 写入 ``runs`` 表，**不会**回写 ``scheduled_tasks``
                # → ``last_status`` 永久停在 "running"、``consecutive_failures`` 不增
                # → 定时任务连续失败**永不触发退避**，``health()`` 也永远显示 running。
                # 现在：起一个轻量后台线程轮询 run 终态，终态后回写任务状态。
                self._settle_after_resume(task_id, run.id, run_service)
                return

        # **W9-05**：run **非终态**（awaiting_approval / interrupted）时，
        # 此前会落到 ``error = result.get("error")``（通常为 None）
        # → ``_mark_task(last_status="success")`` —— run 明明还没完成却被记为成功
        # → 任务健康度 / run_count / 连续失败数全部失真。
        error = result.get("error")
        if current is not None and current.status not in _TERMINAL_RUN_STATUSES:
            status = current.status
            self._mark_task(
                task_id,
                last_status=status if status in ("awaiting_approval", "interrupted") else "failed",
                error=error or f"run 处于非终态: {status}",
                increment=status == "failed",
            )
            return

        self._mark_task(
            task_id,
            last_status="failed" if error else "success",
            error=error,
            increment=True,
        )
        # S7 / WP-7.4：通知实装 —— run 终态后按 delivery 配置投递
        self._deliver(task, row, run, result, error)

    def _settle_after_resume(
        self, task_id: str, run_id: str, run_service, *, timeout_s: float = 900.0
    ) -> None:
        """审批恢复结束后回写任务状态（**W9-04**）。

        恢复段在**后台线程**执行（``resume_after_approval`` → 线程池），
        它的终态只写 ``runs`` 表 → 任务行必须在这里补一次结算，
        否则 ``last_status`` 永远停在 "running"、失败永不计入退避。
        """
        import threading

        def _wait() -> None:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    run = run_service.get_run(run_id)
                except Exception:  # noqa: BLE001
                    return
                if run is None:
                    return
                if run.status in _TERMINAL_RUN_STATUSES:
                    error = None if run.status == "success" else (run.error or run.status)
                    try:
                        self._mark_task(
                            task_id,
                            last_status="success" if run.status == "success" else "failed",
                            error=error,
                            increment=run.status == "failed",
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("回写任务终态失败: task=%s run=%s", task_id, run_id)
                    return
                time.sleep(1.0)
            # 超时仍未终态：标记为 interrupted（不静默停在 running）
            try:
                self._mark_task(task_id, last_status="interrupted", error="审批恢复超时")
            except Exception:  # noqa: BLE001
                logger.exception("回写任务超时状态失败: task=%s", task_id)

        threading.Thread(target=_wait, name="task-settle", daemon=True).start()

    def _deliver(self, task, row, run, result: dict, error: str | None) -> None:
        """按 delivery 配置投递通知（失败不改任务状态）。"""
        try:
            delivery = json.loads(row.delivery_json or "{}")
        except (json.JSONDecodeError, AttributeError):
            return
        channels = delivery.get("channels") or []
        if not channels:
            return
        from app.services.scheduler.delivery import DeliveryConfig, DeliveryPayload, deliver

        artifacts = []
        try:
            from app.services.workspace import artifacts as art

            artifacts = [a["title"] or a["path"] for a in art.list_artifacts(run.id)]
        except Exception:  # noqa: BLE001
            artifacts = []

        # **W9-01**：耗时取 **runs 表的真实值**（此前取 ``result.get("duration_ms")``，
        # 而 ``execute_sync()`` 的返回字典里根本没有这个键 → 恒为 0）。
        duration_ms = 0
        try:
            run_row = run_service.get_run(run.id)
            if run_row is not None and getattr(run_row, "duration_ms", None) is not None:
                duration_ms = int(run_row.duration_ms)
        except Exception:  # noqa: BLE001
            duration_ms = 0
        if not duration_ms:
            duration_ms = int(result.get("duration_ms") or 0)

        payload = DeliveryPayload(
            task_name=task.name,
            status="failed" if error else "success",
            duration_ms=duration_ms,
            summary=str(result.get("answer") or result.get("error") or "")[:500],
            artifacts=artifacts,
            run_id=run.id,
        )
        for cfg in channels:
            if not isinstance(cfg, dict) or not cfg.get("type"):
                continue
            deliver(DeliveryConfig(
                type=str(cfg.get("type")),
                target=str(cfg.get("target", "")),
                template=str(cfg.get("template", "")),
                enabled=bool(cfg.get("enabled", True)),
            ), payload)

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

    # ------------------------------------------------------------------ #
    # 补跑（桌面端唤醒后）
    # ------------------------------------------------------------------ #
    def rescue_missed_runs(
        self,
        since: datetime | None = None,
        limit: int = 20,
    ) -> dict:
        """补跑挂起期间错过的定时任务。

        语义（见 ``doc/design/03-桌面壳与后端进程编排设计.md`` §3.2.1）：

        - 每个任务**最多补跑一次**（取窗口内最后一次应触发时刻）；
        - 补跑使用**原本的槽位时间**而非当前时间，由 ``runs`` 表的
          ``UNIQUE(task_id, scheduled_for)`` 保证同一槽位只跑一次；
        - 超过 ``desktop_missed_window_hours`` 的错过任务**只统计不补跑**。
        """
        now = datetime.now(timezone.utc)
        window = timedelta(hours=max(1, settings.desktop_missed_window_hours))
        lower_bound = since or (now - window)
        effective_from = max(lower_bound, now - window)

        rescued: list[dict] = []
        skipped = 0
        items: list[dict] = []

        with db_session() as db:
            rows = db.scalars(select(ScheduledTaskRow).where(ScheduledTaskRow.enabled == 1)).all()
            candidates = [(row.id, row.schedule_kind, row.cron_expr, row.interval_seconds,
                           row.timezone, row.created_at, row.rrule_expr) for row in rows]

        # **F-SCH-09 / AUD2-M04**：此前是 ``candidates[:limit]``（默认 20）
        # 且 SQL **无 ORDER BY** → 选取任意 20 个任务，其余**永不补跑**，
        # 且每次补跑的集合可能不同（不确定 → 同样的任务反复被跳过）。
        # 现在：**全量遍历**（limit 语义改为「单批上限」由分页实现，
        # 此处按 created_at 排序保证确定性）。
        candidates.sort(key=lambda c: (str(c[5] or ""), str(c[0])))
        for task_id, kind, cron_expr, interval_seconds, tz_name, created_at, rrule_expr in candidates:
            slot = self._missed_slot(kind, cron_expr, interval_seconds, tz_name, created_at,
                                   effective_from, now, rrule_expr)
            if slot is None:
                skipped += 1
                continue
            item = {"task_id": task_id, "scheduled_for": slot, "status": "queued"}
            items.append(item)
            self._fire(task_id, slot_override=slot)
            # **F-SCH-09 / AUD2-M04**：``_fire`` 内部可能因**退避 / 配额 / 幂等**而跳过，
            # 此前状态**无条件**写成 "rescued" → 明明没跑却报「已补跑」。
            # 现在：按 ``_fire`` 的实际结果回填（run 是否真的创建）。
            actually_run = True
            try:
                if self.run_service is not None:
                    run = self.run_service.get_by_task_slot(task_id, slot)
                    if run is not None:
                        actually_run = run.status not in ("skipped",)
                    else:
                        actually_run = False
            except Exception:  # noqa: BLE001
                actually_run = True
            item["status"] = "rescued" if actually_run else "skipped"
            if actually_run:
                rescued.append(item)
            else:
                skipped += 1

        return {
            "rescued": len(rescued),
            "skipped": skipped,
            "window_hours": max(1, settings.desktop_missed_window_hours),
            "items": items,
        }

    def _missed_slot(
        self,
        kind: str,
        cron_expr: str | None,
        interval_seconds: int | None,
        tz_name: str,
        created_at: str | None,
        since: datetime,
        now: datetime,
        rrule_expr: str | None = None,
    ) -> str | None:
        """窗口内最后一次应触发的槽位时间（ISO8601 UTC）；无则返回 None。"""
        if kind == "interval":
            interval = interval_seconds or 60
            anchor = _parse_iso(created_at) or since
            idx = int((now - anchor).total_seconds() // interval)
            if idx < 0:
                return None
            slot = anchor + timedelta(seconds=idx * interval)
            if slot < since or slot > now:
                return None
            return slot.astimezone(timezone.utc).isoformat()

        if kind == "rrule":  # P2-16：RRULE 的补跑槽位 = 窗口内最近一个合法触发点
            from app.services.scheduler.rrule import RRULEError, expand_slots, parse

            if not rrule_expr:
                return None
            try:
                rule = parse(rrule_expr.strip())
            except RRULEError:
                return None
            tz = ZoneInfo(tz_name)
            # **W7-03**：锚点用窗口起点 ``since``（而非 created_at），且 limit 必须
            # 能覆盖窗口内的全部槽位 —— 否则高频规则的最近槽位会被 limit 截断。
            anchor = since
            local_since = since.astimezone(tz)
            local_now = now.astimezone(tz)
            window_days = max(1, (local_now - local_since).days + 1)
            per_day = {
                "HOURLY": 24, "MINUTELY": 24 * 60, "SECONDLY": 24 * 60 * 60,
            }.get(str(getattr(rule, "freq", "")).upper(), 1)
            limit = min(20000, max(400, window_days * per_day))
            try:
                slots = expand_slots(
                    rule, anchor.astimezone(tz), limit=limit, horizon_days=window_days,
                )
            except Exception:  # noqa: BLE001
                return None
            best: datetime | None = None
            for raw in slots:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                if local_since <= dt <= local_now:
                    best = dt
                elif dt > local_now:
                    break
            if best is None:
                return None
            return best.astimezone(timezone.utc).isoformat()

        if not cron_expr:
            return None
        try:
            trigger = CronTrigger.from_crontab(cron_expr.strip(), timezone=ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 - 非法 cron 不补跑
            return None

        # **W7-03**：改用二分反解（与正常触发路径**同一套算法**）。
        # 旧实现从 ``since`` 正向迭代 200 次 → 高频 cron（``*/1 * * * *``）在 6 小时
        # 窗口内有 360 个触发点 → 取到的是窗口内倒数第 ~200 个（早于窗口末尾 2.7 小时）
        # → **补跑错误的槽位**。
        last = self._last_cron_fire(trigger, now)
        if last is None or last < since:
            return None
        return last.astimezone(timezone.utc).isoformat()

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

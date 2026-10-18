"""RunService —— 运行账本与事件回放（runs / run_events）。

- 统一承载手动 / 定时 / API 三种触发的运行；
- 事件批量写入（每 20 条或 2 秒 flush 一次），避免逐条事务拖慢 SSE；
- Plan 模式状态机：awaiting_approval → approve / reject。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import db_session, retry_on_locked
from app.db.models import RunEventRow, RunRow, new_id, utc_now
from app.schemas.run import RunEventOut, RunOut

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"success", "failed", "skipped", "interrupted", "rejected"}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def run_to_out(row: RunRow) -> RunOut:
    return RunOut(
        id=row.id,
        task_id=row.task_id,
        session_id=row.session_id,
        trigger=row.trigger,
        scheduled_for=row.scheduled_for,
        status=row.status,  # type: ignore[arg-type]
        plan=json.loads(row.plan_json) if row.plan_json else None,
        meta=json.loads(row.meta_json or "{}"),
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=row.duration_ms,
        result_summary=row.result_summary,
        error=row.error,
        files=json.loads(row.files_json or "[]"),
        created_at=row.created_at,
    )


class RunService:
    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def create_run(
        self,
        *,
        trigger: str = "api",
        task_id: str | None = None,
        session_id: str | None = None,
        scheduled_for: str | None = None,
        status: str = "queued",
        meta: dict | None = None,
    ) -> RunOut | None:
        """创建运行记录；幂等冲突（同 task 同 slot）返回 None。"""
        row = RunRow(
            trigger=trigger,
            task_id=task_id,
            session_id=session_id,
            scheduled_for=scheduled_for,
            status=status,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
        )
        try:
            with db_session() as db:
                db.add(row)
                db.flush()
                db.refresh(row)
                return run_to_out(row)
        except IntegrityError:
            logger.info("运行幂等冲突，跳过: task=%s slot=%s", task_id, scheduled_for)
            return None

    def get_run(self, run_id: str) -> RunOut | None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            return run_to_out(row) if row else None

    def update_meta(self, run_id: str, meta: dict) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row:
                row.meta_json = json.dumps(meta, ensure_ascii=False)

    def attach_session(self, run_id: str, session_id: str) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row and not row.session_id:
                row.session_id = session_id

    def mark_running(self, run_id: str) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row:
                row.status = "running"
                row.started_at = utc_now()

    def save_plan(self, run_id: str, plan: list[dict]) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row:
                row.plan_json = json.dumps(plan, ensure_ascii=False)
                row.status = "awaiting_approval"

    def approve_plan(self, run_id: str, edited_plan: list[dict] | None = None) -> RunOut | None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row is None or row.status != "awaiting_approval":
                return None
            if edited_plan is not None:
                row.plan_json = json.dumps(edited_plan, ensure_ascii=False)
                meta = json.loads(row.meta_json or "{}")
                meta["plan_edited"] = True
                row.meta_json = json.dumps(meta, ensure_ascii=False)
            row.status = "queued"
            db.flush()
            db.refresh(row)
            return run_to_out(row)

    def reject_run(self, run_id: str, reason: str = "") -> RunOut | None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row is None or row.status != "awaiting_approval":
                return None
            row.status = "rejected"
            row.error = reason or "用户拒绝了计划"
            row.finished_at = utc_now()
            db.flush()
            db.refresh(row)
            return run_to_out(row)

    def finish(
        self,
        run_id: str,
        status: str,
        summary: str = "",
        files: list | None = None,
        error: str | None = None,
    ) -> None:
        def _update() -> None:
            with db_session() as db:
                row = db.get(RunRow, run_id)
                if row is None:
                    return
                row.status = status
                row.finished_at = utc_now()
                started = _parse_iso(row.started_at)
                if started:
                    row.duration_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds() * 1000
                    )
                if summary:
                    row.result_summary = summary[:2000]
                if files is not None:
                    row.files_json = json.dumps(files, ensure_ascii=False)
                if error:
                    row.error = error[:2000]

        retry_on_locked(_update)

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def append_events(self, run_id: str, events: list[dict]) -> None:
        if not events:
            return

        def _write() -> None:
            with db_session() as db:
                max_seq = db.scalar(
                    select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
                ) or 0
                for i, ev in enumerate(events, start=1):
                    payload = {k: v for k, v in ev.items() if k != "type"}
                    db.add(
                        RunEventRow(
                            run_id=run_id,
                            seq=max_seq + i,
                            type=ev.get("type", "unknown"),
                            payload_json=json.dumps(payload, ensure_ascii=False, default=str)[:60000],
                        )
                    )

        retry_on_locked(_write)

    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> tuple[list[RunEventOut], int, str]:
        with db_session() as db:
            rows = db.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
                .order_by(RunEventRow.seq)
                .limit(limit + 1)
            ).all()
            status = db.scalar(select(RunRow.status).where(RunRow.id == run_id)) or "unknown"
            has_more = len(rows) > limit
            rows = rows[:limit]
            items = [
                RunEventOut(
                    seq=r.seq,
                    type=r.type,
                    payload=json.loads(r.payload_json or "{}"),
                    created_at=r.created_at,
                )
                for r in rows
            ]
            last_seq = rows[-1].seq if rows else after_seq
            return items, last_seq, status

    def list_runs(
        self,
        task_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[RunOut], int]:
        with db_session() as db:
            stmt = select(RunRow)
            if task_id:
                stmt = stmt.where(RunRow.task_id == task_id)
            total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = db.scalars(
                stmt.order_by(RunRow.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [run_to_out(r) for r in rows], total

    # ------------------------------------------------------------------ #
    # 调度辅助
    # ------------------------------------------------------------------ #
    def count_today_runs(self, task_id: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with db_session() as db:
            return db.scalar(
                select(func.count())
                .select_from(RunRow)
                .where(
                    RunRow.task_id == task_id,
                    RunRow.started_at >= today,
                    RunRow.status.in_(("running", "success", "failed", "awaiting_approval")),
                )
            ) or 0

    def recover_interrupted(self, grace_seconds: int = 300) -> int:
        """重启恢复：running 超过宽限期的标记为 interrupted。"""
        threshold = datetime.fromtimestamp(
            time.time() - grace_seconds, tz=timezone.utc
        ).isoformat()
        with db_session() as db:
            rows = db.scalars(
                select(RunRow).where(RunRow.status.in_(("queued", "running")))
            ).all()
            count = 0
            for row in rows:
                ref = row.started_at or row.created_at
                if ref < threshold:
                    row.status = "interrupted"
                    row.error = (row.error or "") + " 服务重启，标记为中断"
                    row.finished_at = utc_now()
                    count += 1
            return count

    def interrupt_run(self, run_id: str) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row and row.status in ("queued", "running"):
                row.status = "interrupted"
                row.finished_at = utc_now()

    def cleanup(self, retention_days: int = 90, keep_per_task: int = 500) -> int:
        """清理过期运行记录（级联删除事件）。返回删除条数。"""
        cutoff = datetime.fromtimestamp(
            time.time() - retention_days * 86400, tz=timezone.utc
        ).isoformat()
        removed = 0
        with db_session() as db:
            old = db.scalars(
                select(RunRow).where(
                    RunRow.created_at < cutoff,
                    RunRow.status.in_(tuple(TERMINAL_STATUSES)),
                )
            ).all()
            for row in old:
                db.delete(row)
                removed += 1
        return removed

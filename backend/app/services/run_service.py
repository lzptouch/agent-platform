"""RunService —— 运行账本与事件回放（runs / run_events）。

- 统一承载手动 / 定时 / API 三种触发的运行；
- 事件批量写入（每 20 条或 2 秒 flush 一次），避免逐条事务拖慢 SSE；
- Plan 模式状态机：awaiting_approval → approve / reject。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import db_session, retry_on_locked
from app.db.models import RunEventRow, RunRow, new_id, utc_now
from app.schemas.run import RunEventOut, RunOut

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"success", "failed", "skipped", "interrupted", "rejected"}


def _zone(tz: str | None):
    """时区解析：非法时区回落 UTC（不抛，避免配额统计被一个坏配置打断）。"""
    if not tz:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return timezone.utc


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
        workspace_id: str | None = None,
    ) -> RunOut | None:
        """创建运行记录；幂等冲突（同 task 同 slot）返回 None。

        工作空间绑定（S3 / WP-3.2）：``workspace_id`` 显式指定则用之；否则用
        **当前工作空间**（无当前空间则用全局工作目录）。绑定结果写入
        ``meta_json.workspace_id`` / ``meta_json.workspace_root``，运行期锁定。
        """
        meta = dict(meta or {})
        if "workspace_id" not in meta:
            ws_id, ws_root = self._bind_workspace(workspace_id)
            meta["workspace_id"] = ws_id
            meta["workspace_root"] = str(ws_root)
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

    @staticmethod
    def _bind_workspace(workspace_id: str | None) -> tuple[str | None, "Path"]:
        """解析 run 的工作空间：显式指定 → 当前空间 → 全局工作目录。"""
        from pathlib import Path

        from app.core.workspace import get_workspace_dir
        from app.services.workspace.service import WorkspaceService

        svc = WorkspaceService.instance()
        if workspace_id:
            ws = svc.get(workspace_id)
            if ws is None:
                raise ValueError(f"工作空间不存在: {workspace_id}")
            return ws.id, Path(ws.root_path)
        current = svc.current()
        if current is not None:
            # 用户**显式切换**过工作空间 → 遵从用户意图
            return current.id, Path(current.root_path)
        # P2-19：未显式切换 → **自动创建独立工作区**（``wb-{日期}-{短ID}``）。
        # 此前走 ``get_workspace_dir()``（全局目录）→ 新任务不会得到独立目录，
        # 「一任务一工作空间」不成立，且 ``meta.workspace_id`` 为空。
        ws_id, ws_root = svc.bind_for_run(None)
        return ws_id, Path(ws_root)

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
        """批准计划 → 状态转 ``queued``。

        **P3-15**：同时把**恢复参数**写入 ``meta_json``（含 ``resume_of``
        指向与 ``approved_at``）——这样进程重启后能扫描并续跑
        （此前用 daemon 线程，进程退出执行即丢）。
        """
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row is None or row.status != "awaiting_approval":
                return None
            meta = json.loads(row.meta_json or "{}")
            if edited_plan is not None:
                row.plan_json = json.dumps(edited_plan, ensure_ascii=False)
                meta["plan_edited"] = True
            meta["resume_of"] = run_id
            meta["approved_at"] = utc_now()
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
                # **W2-03 / AUD-H06（终态守卫）**
                # 此前 `finish()` **无条件**改写 status → 迟到的 `finish("success")`
                # 会覆盖 `interrupt_run()` 写入的 `interrupted`、或 `reject_run()` 的
                # `rejected` → 用户明明取消了，run 却显示成功。
                # 现在：**已处于终态则不再改写 status**，只补齐 finished_at 等附属信息。
                already_terminal = row.status in TERMINAL_STATUSES
                if not already_terminal:
                    row.status = status
                row.finished_at = utc_now()
                # S5 / WP-5.5.4：用量聚合（token / 成本写入 runs）
                # **W2-03**：`aggregate_run` 已改为**纯读**（此前它在自己的 session 里
                # 写回本行 → version_id 自增 → 本 session 的 flush 匹配 0 行
                # → StaleDataError → 收尾整体失败）。
                try:
                    from app.services.exec.accounting import aggregate_run

                    agg = aggregate_run(run_id)
                    if agg.get("llm_calls"):
                        row.prompt_tokens = agg["prompt_tokens"]
                        row.completion_tokens = agg["completion_tokens"]
                        row.llm_calls = agg["llm_calls"]
                        row.estimated_cost = agg["estimated_cost"]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("用量聚合失败（不影响收尾）: %s", exc)
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
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[RunOut], int]:
        """运行记录列表（可按 ``task_id`` 与 ``status`` 过滤）。

        S4：``GET /runs?status=running`` 用于并行任务观察（不新增 `/runs/active`，
        那条路径会被 `/{run_id}` 捕获，见 `../design/05` §3.4）。
        """
        with db_session() as db:
            stmt = select(RunRow)
            if task_id:
                stmt = stmt.where(RunRow.task_id == task_id)
            if status:
                stmt = stmt.where(RunRow.status == status)
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
    def get_by_task_slot(self, task_id: str, scheduled_for: str) -> RunOut | None:
        """按 ``(task_id, scheduled_for)`` 取 run（幂等槽位查询）。

        **F-SCH-09 / AUD2-M04**：补跑需要知道「这次到底跑没跑」，
        以此回填状态（此前无条件写 "rescued"，明明被跳过也报已补跑）。
        """
        from sqlalchemy import select

        with db_session() as db:
            row = db.scalar(
                select(RunRow).where(
                    RunRow.task_id == task_id,
                    RunRow.scheduled_for == scheduled_for,
                )
            )
            return run_to_out(row) if row is not None else None

    def count_today_runs(self, task_id: str, tz: str | None = None) -> int:
        """统计任务「今天」的运行数（**按任务时区**的本地自然日）。

        旧实现用 UTC 日期，与 ``scheduled_tasks.timezone`` 不一致：跨时区任务会在
        本地零点前就被判成「今天已跑满」。这里按任务时区切出本地零点，再折算回
        UTC 边界做区间过滤。
        """
        zone = _zone(tz)
        now_local = datetime.now(zone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        end_utc = end_local.astimezone(timezone.utc).isoformat()
        with db_session() as db:
            return db.scalar(
                select(func.count())
                .select_from(RunRow)
                .where(
                    RunRow.task_id == task_id,
                    RunRow.started_at >= start_utc,
                    RunRow.started_at < end_utc,
                    RunRow.status.in_(("running", "success", "failed", "awaiting_approval")),
                )
            ) or 0

    def recover_interrupted(
        self, grace_seconds: int = 300, reason: str = "服务重启，标记为中断"
    ) -> int:
        """把超期未完成的 run 标记为 interrupted。

        - 启动时调用（``reason`` = 服务重启）；
        - 调度器周期巡检也调用（``reason`` = 超过时限未完成）——
          崩溃残留的 ``running`` 不再永久停留（S-08-08）。
        """
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
                    row.error = (row.error or "") + " " + reason
                    row.finished_at = utc_now()
                    count += 1
            return count

    def aggregate_usage(self, run_id: str) -> dict:
        """把该 run 的 LLM 计量聚合到 runs 行（S5 / WP-5.5.4）。"""
        try:
            from app.services.exec.accounting import aggregate_run

            return aggregate_run(run_id)
        except Exception as exc:  # noqa: BLE001 —— 聚合失败不影响主流程
            logger.warning("用量聚合失败: %s", exc)
            return {}

    def interrupt_run(self, run_id: str) -> None:
        with db_session() as db:
            row = db.get(RunRow, run_id)
            if row and row.status in ("queued", "running"):
                row.status = "interrupted"
                row.finished_at = utc_now()

    def cleanup(self, retention_days: int = 90, keep_per_task: int = 500) -> int:
        """清理过期运行记录（级联删除事件）。返回删除条数。

        **P3-09**：``keep_per_task`` 此前**被声明但从未使用**——只按时间删。
        现在实现两条语义：

        ① **时间维度**：早于 ``retention_days`` 的**终态** run 删除；
        ② **每任务维度**：每个任务只保留**最近 N 条终态 run**，
           超出的部分**即使未到保留期也删**（防止高频任务无限膨胀）。

        未到保留期的**其他任务**记录不受影响（只裁剪超出配额的）。
        """
        cutoff = datetime.fromtimestamp(
            time.time() - retention_days * 86400, tz=timezone.utc
        ).isoformat()
        removed = 0
        with db_session() as db:
            doomed: dict[str, RunRow] = {}

            # ① 时间维度
            for row in db.scalars(
                select(RunRow).where(
                    RunRow.created_at < cutoff,
                    RunRow.status.in_(tuple(TERMINAL_STATUSES)),
                )
            ).all():
                doomed[row.id] = row

            # ② 每任务维度：只保留最近 N 条终态 run
            if keep_per_task > 0:
                task_ids = db.scalars(
                    select(RunRow.task_id)
                    .where(
                        RunRow.task_id.is_not(None),
                        RunRow.status.in_(tuple(TERMINAL_STATUSES)),
                    )
                    .distinct()
                ).all()
                for tid in task_ids:
                    rows = db.scalars(
                        select(RunRow)
                        .where(
                            RunRow.task_id == tid,
                            RunRow.status.in_(tuple(TERMINAL_STATUSES)),
                        )
                        .order_by(RunRow.created_at.desc(), RunRow.id.desc())
                    ).all()
                    for row in rows[keep_per_task:]:
                        doomed.setdefault(row.id, row)

            for row in doomed.values():
                db.delete(row)
                removed += 1
        return removed

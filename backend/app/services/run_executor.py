"""RunExecutor —— 「Agent 执行 + 落库」编排层。

- 供 HTTP（SSE / 阻塞）与定时任务复用；
- **DB Session 在生成器内部创建**（StreamingResponse 返回后 FastAPI 依赖已释放）；
- 事件批量入库；结束时写 assistant 消息 + 更新 run 状态；
- 客户端断开 → run 标记 interrupted；异常 → failed。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.logging import bind_context, reset_context

if TYPE_CHECKING:
    from app.services.agent_service import AgentService
    from app.services.run_service import RunService
    from app.services.session_service import SessionService
    from app.services.team_service import TeamService

logger = logging.getLogger(__name__)

EVENT_FLUSH_COUNT = 20
EVENT_FLUSH_INTERVAL = 2.0

#: P1-07：**显式终止原因**——这些终态由用户的显式动作产生，优先级高于 ``error``。
#: 取消（interrupted）时 ``error`` 字段仍记录取消原因供 UI 展示，
#: 但**不再把终态覆盖为 failed**（此前 ``if error: final_status="failed"`` 无条件覆盖，
#: 导致用户点「停止」后 run 终态变成 failed 而非 interrupted）。
EXPLICIT_TERMINAL_STATUSES = {"interrupted", "rejected", "skipped"}


class RunExecutor:
    def __init__(
        self,
        agent_service: AgentService,
        session_service: SessionService,
        run_service: RunService,
        team_service: TeamService | None = None,
    ) -> None:
        self.agent_service = agent_service
        self.session_service = session_service
        self.run_service = run_service
        self.team_service = team_service
        # 全局并发护栏（仅调度/阻塞执行使用，交互式 SSE 不占用）
        # P3-01：**两个独立预算**——交互（HTTP/前端）与调度（定时）互不占用。
        # 交互请求**排队等待**槽位（超时才回 busy）；调度请求满了直接 busy。
        self._schedule_semaphore = threading.BoundedSemaphore(
            settings.schedule_max_concurrent,
        )
        # P3-15：**受控线程池**替代裸 daemon 线程——
        # daemon 线程在进程退出时被直接杀掉，恢复中的执行**静默丢失**；
        # 线程池可等待完成（优雅退出），且并发天然受 ``schedule_max_concurrent`` 约束。
        self._resume_pool = ThreadPoolExecutor(
            max_workers=max(1, settings.schedule_max_concurrent),
            thread_name_prefix="run-resume",
        )
        self._interactive_semaphore = threading.BoundedSemaphore(
            settings.interactive_max_concurrent,
        )
        # 运行控制：steer 待注入指令 / cancel 中止标志（按 run_id）
        self._steer_queue: dict[str, list[str]] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._control_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 运行控制（中止 / 介入转向）
    # ------------------------------------------------------------------ #
    def request_cancel(self, run_id: str) -> bool:
        """请求中止运行。

        置位取消标志（下一轮迭代起点生效）+ 把 run 状态改为 ``interrupted``。
        **已知边界**：正在执行的 ``subprocess.run``（阻塞式，最长 180 秒）
        不会被立即终止——状态先落 ``interrupted``，命令跑完后才真正结束。
        """
        with self._control_lock:
            flag = self._cancel_flags.setdefault(run_id, threading.Event())
            flag.set()
        self.run_service.interrupt_run(run_id)
        return True

    def request_steer(self, run_id: str, instruction: str, mode: str = "append") -> bool:
        """请求在下一轮并入一条转向指令（不中止本次运行）。

        ``mode``：
        - ``append``：追加约束（默认）；
        - ``replace_plan``：丢弃当前计划，回到规划步骤重新出方案。

        队列按入队顺序消费（``seq`` 保序），多次 steer 不会错配轮次。
        """
        text = (instruction or "").strip()
        if not text:
            return False
        mode = mode if mode in ("append", "replace_plan") else "append"
        with self._control_lock:
            queue = self._steer_queue.setdefault(run_id, [])
            queue.append({"text": text, "mode": mode, "seq": len(queue) + 1})
        return True

    def is_cancelled(self, run_id: str) -> bool:
        with self._control_lock:
            flag = self._cancel_flags.get(run_id)
            return bool(flag and flag.is_set())

    def _steer_hook(self, run_id: str):
        def hook() -> list[dict]:
            with self._control_lock:
                pending = self._steer_queue.get(run_id)
                if not pending:
                    return []
                # 取出即清空（一次性消费），按 seq 保序
                self._steer_queue[run_id] = []
                return sorted(list(pending), key=lambda x: x.get("seq", 0))

        return hook

    def _cancel_hook(self, run_id: str):
        def hook() -> bool:
            return self.is_cancelled(run_id)

        return hook

    # ------------------------------------------------------------------ #
    # 流式执行（HTTP SSE）
    # ------------------------------------------------------------------ #
    def execute_stream(
        self,
        prompt: str,
        *,
        mode: str = "work",
        session_id: str | None = None,
        team_id: str | None = None,
        plan_first: bool = False,
        model: str | None = None,
        skills: list[str] | None = None,
        enable_mcp: bool = False,
        mcp_servers: list[str] | None = None,
        enable_rag: bool = False,
        enable_web_research: bool = False,
        enable_reflection: bool = False,
        role_id: int | None = None,   # P2-10：按角色运行
        debug_prompt: bool = False,   # P4-06：调试模式全量下发 prompt
        trigger: str = "api",
        task_id: str | None = None,
        scheduled_for: str | None = None,
        deadline: float | None = None,
        run_id: str | None = None,
        acquire_slot: bool = True,
    ) -> Iterator[dict]:
        """执行一次流式运行。

        ``acquire_slot``：是否占用**并发预算**槽位。交互路径（HTTP/前端）默认占用，
        与调度路径共享同一信号量（S4 / WP-4.4）；``execute_sync`` 自己已持有槽位，
        传 ``False`` 避免重复占用导致预算被折半。
        """
        from app.services.workspace.service import current_run_context

        ws_ctx_active = False  # 在 finally 中复位（早退路径也安全）
        slot_acquired = False  # 并发预算槽位（finally 中释放）
        slot_sem = None

        def _release_slot() -> None:
            """释放并发槽位（**幂等**）。

            **W2-01 / AUD-C03（早退路径泄漏槽位）**

            此前槽位在 ``:167`` 获取、在内层 ``try/finally``（``:379``）释放，
            但那个 ``try`` **从 ``:318`` 才开始** → 位于其前的 5 条早退分支
            （团队不存在 / 会话不存在 / chat 会话不支持 plan_first /
            幂等冲突 / 预创建 run 不存在）**全部绕过 finally** →
            每 4 次这样的错误请求就把 ``interactive_max_concurrent=4``
            的槽位**全部泄漏** → 交互式运行**永久 busy**（调度路径仍正常）。
            """
            nonlocal slot_acquired, slot_sem
            if slot_acquired and slot_sem is not None:
                slot_sem.release()
                slot_acquired = False
                slot_sem = None

        def _fail(content: str) -> Iterator[dict]:
            """统一的早退出口：**先释放槽位**再产出 error/done。"""
            _release_slot()
            yield {"type": "error", "content": content}
            yield {"type": "done"}

        if acquire_slot:
            slot_sem, acquired, slot_limit = self._acquire_slot(trigger)
            if not acquired:
                # 并发预算已满 → 明确告知（不静默丢弃）
                yield {
                    "type": "busy",
                    "content": "busy: 并发已达上限，请稍后重试",
                    "limit": slot_limit,
                }
                yield {"type": "done"}
                return
            slot_acquired = True
        # ---- 团队解析（先拿到 skills 列表）----
        team_meta: dict | None = None
        resolved_skills = skills
        warnings: list[str] = []
        if team_id and self.team_service is not None:
            try:
                resolved_skills, team_meta, warnings = self.team_service.resolve_for_agent(
                    team_id, query=prompt, mode=mode
                )
            except KeyError:
                yield from _fail(f"团队不存在: {team_id}")
                return

        # ---- 会话 ----
        session = None
        if session_id:
            session = self.session_service.get(session_id, message_limit=0)
            if session is None:
                yield from _fail(f"会话不存在: {session_id}")
                return
            mode = session.mode  # 会话模式不可变
            if plan_first and mode == "chat":
                yield from _fail("该会话是对话模式，不支持计划审批；请新建工作模式会话")
                return
            if session.team_id and not team_id and self.team_service is not None:
                try:
                    resolved_skills, team_meta, warnings = self.team_service.resolve_for_agent(
                        session.team_id, query=prompt, mode=mode
                    )
                except KeyError:
                    pass
        else:
            session = self.session_service.create(mode=mode, team_id=team_id)
            session_id = session.id
            if run_id is not None:
                self.run_service.attach_session(run_id, session_id)

        # ---- 运行记录 ----
        if run_id is None:
            run = self.run_service.create_run(
                trigger=trigger,
                task_id=task_id,
                session_id=session_id,
                scheduled_for=scheduled_for,
                status="running",
                meta={
                    "prompt": prompt,
                    "mode": mode,
                    "model": model or settings.default_model,
                    "team_id": team_id,
                    "skills": resolved_skills,
                    "enable_mcp": enable_mcp,
                    "mcp_servers": mcp_servers or [],
                    "enable_rag": enable_rag,
                    "enable_web_research": enable_web_research,
                    "enable_reflection": enable_reflection,
                    "plan_first": plan_first,
                },
            )
            if run is None:
                _release_slot()
                yield {"type": "notice", "content": "相同调度槽位已存在运行记录，跳过"}
                yield {"type": "done"}
                return
            run_id = run.id
        else:
            # 预创建 run（调度器幂等闸门）：补充 meta 便于审批恢复
            existing = self.run_service.get_run(run_id)
            if existing is None:
                yield from _fail(f"运行记录不存在: {run_id}")
                return
            meta = dict(existing.meta)
            meta.setdefault("prompt", prompt)
            meta.setdefault("mode", mode)
            meta.setdefault("model", model or settings.default_model)
            meta.setdefault("team_id", team_id)
            meta.setdefault("skills", resolved_skills)
            meta.setdefault("enable_mcp", enable_mcp)
            meta.setdefault("mcp_servers", mcp_servers or [])
            meta.setdefault("enable_rag", enable_rag)
            meta.setdefault("enable_web_research", enable_web_research)
            meta.setdefault("enable_reflection", enable_reflection)
            meta.setdefault("plan_first", plan_first)
            self.run_service.update_meta(run_id, meta)
        self.run_service.mark_running(run_id)
        # 日志上下文：让落盘日志能按 run_id / session_id 检索（批次 03 / WP-3.2）
        log_ctx_token = bind_context(run_id=run_id, session_id=session_id)

        yield {
            "type": "meta",
            "run_id": run_id,
            "session_id": session_id,
            "mode": mode,
            "team": team_meta,
            "resolved_skills": resolved_skills or [],
        }
        for w in warnings:
            yield {"type": "notice", "content": w}

        # ---- 落 user 消息 + 历史 ----
        self.session_service.append_message(session_id, "user", prompt, run_id=run_id)
        history = self.session_service.build_history(session_id)
        # build_history 已包含刚写入的 user 消息，去掉最后一条避免重复
        if history and history[-1]["role"] == "user" and history[-1]["content"] == prompt:
            history = history[:-1]

        # ---- 执行（设置 run 的工作空间上下文，工具层据此做写前快照） ----
        run_meta = self.run_service.get_run(run_id)
        ws_ctx = None
        if run_meta is not None:
            meta_obj = run_meta.meta or {}
            if meta_obj.get("workspace_root"):
                ws_ctx = {
                    "run_id": run_id,
                    "workspace_id": meta_obj.get("workspace_id"),
                    "workspace_root": meta_obj["workspace_root"],
                }
        if ws_ctx:
            # 生成器跨上下文迭代时 Token.reset 会报 ValueError —— 用 set(None) 复位
            current_run_context.set(ws_ctx)
            ws_ctx_active = True

        buffer: list[dict] = []
        last_flush = time.monotonic()
        answer_parts: list[str] = []
        steps: list[dict] = []
        files: list[dict] = []
        error: str | None = None
        final_status = "success"

        def flush() -> None:
            nonlocal last_flush
            if buffer:
                self.run_service.append_events(run_id, list(buffer))
                buffer.clear()
                last_flush = time.monotonic()

        try:
            stream = self.agent_service.stream(
                prompt,
                model,
                skills=resolved_skills,
                enable_mcp=enable_mcp,
                mcp_servers=mcp_servers,
                enable_rag=enable_rag,
                enable_web_research=enable_web_research,
                enable_reflection=enable_reflection,
                role_id=role_id,
                debug_prompt=debug_prompt,
                mode=mode,
                history=history,
                team=team_meta,
                plan_first=plan_first,
                deadline=deadline,
                steer_hook=self._steer_hook(run_id),
                cancel_hook=self._cancel_hook(run_id),
                # **W2-02**：把 run / session 归属传下去。
                # 此前**两处都没传** → `agent_service` 里 `self._current_run_id = None`
                # → `record_call(run_id=None)` → `llm_calls.run_id` **恒为 NULL**
                # → `runs.prompt_tokens / completion_tokens / llm_calls / estimated_cost`
                #   **永远 NULL/0**，`GET /runs/{id}/cost` 恒返回空明细。
                run_id=run_id,
                session_id=session_id,
            )
            for event in stream:
                etype = event.get("type")
                if etype == "model_text":
                    answer_parts.append(event.get("content", ""))
                elif etype in ("tool_call", "tool_result", "plan", "reflection_plan"):
                    steps.append({"type": etype, **{k: v for k, v in event.items() if k != "type"}})
                elif etype == "files":
                    files = event.get("files", [])
                elif etype == "interrupted":
                    # S4：取消在工具边界生效 → 终态 interrupted（不是 failed）
                    final_status = "interrupted"
                    error = event.get("content") or "运行已被取消"
                    yield event
                elif etype == "error":
                    error = event.get("content", "unknown error")
                elif etype == "approval_required":
                    plan = event.get("plan", [])
                    self.run_service.save_plan(run_id, plan)
                    final_status = "awaiting_approval"
                    yield {"type": "approval_required", "run_id": run_id, "plan": plan}
                    buffer.append(event)
                    flush()
                    self.run_service.finish(run_id, "awaiting_approval", summary="等待计划审批")
                    return
                elif etype == "done" and event.get("status") == "awaiting_approval":
                    continue

                buffer.append(event)
                yield event
                if len(buffer) >= EVENT_FLUSH_COUNT or time.monotonic() - last_flush > EVENT_FLUSH_INTERVAL:
                    flush()
        except GeneratorExit:
            self.run_service.interrupt_run(run_id)
            flush()
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("运行执行失败: %s", run_id)
            error = f"{type(exc).__name__}: {exc}"
            final_status = "failed"
            yield {"type": "error", "content": error}
            yield {"type": "done"}
        finally:
            flush()
            if ws_ctx_active:
                current_run_context.set(None)
            if slot_acquired and slot_sem is not None:
                slot_sem.release()
            reset_context(log_ctx_token)

        # P1-07：终态优先级 —— 显式终止原因（interrupted/rejected/skipped）> error。
        # 取消时 error 保留取消原因供 UI 展示，但终态保持 interrupted。
        if error and final_status not in EXPLICIT_TERMINAL_STATUSES:
            final_status = "failed"

        # ---- 落 assistant 消息 + 收尾 ----
        answer = "".join(answer_parts)
        if final_status == "success" or answer:
            self.session_service.append_message(
                session_id,
                "assistant",
                answer,
                run_id=run_id,
                steps=steps[-20:],
                files=files,
                meta={"mode": mode, "error": error},
            )
        self.run_service.finish(
            run_id,
            final_status,
            summary=answer[:500] or (error or ""),
            files=files,
            error=error,
        )

    # ------------------------------------------------------------------ #
    # 并发预算（P3-01：交互 / 调度两套预算，互不占用）
    # ------------------------------------------------------------------ #
    def _acquire_slot(self, trigger: str):
        """按触发来源取并发槽位。

        - ``schedule``：用**调度预算**（2 个），满了**立即** busy（不让定时任务排队）；
        - 其余（交互）：用**交互预算**（4 个），**排队等待**
          （``interactive_queue_timeout`` 秒），超时才回 busy。

        :return: ``(semaphore, acquired, limit)``；未获取到时 ``semaphore`` 为 ``None``。
        """
        if trigger == "schedule":
            sem = self._schedule_semaphore
            limit = settings.schedule_max_concurrent
            return sem, sem.acquire(blocking=False), limit
        sem = self._interactive_semaphore
        limit = settings.interactive_max_concurrent
        acquired = sem.acquire(
            blocking=True, timeout=settings.interactive_queue_timeout,
        )
        return sem, acquired, limit

    # ------------------------------------------------------------------ #
    # 阻塞执行（脚本 / 定时任务）
    # ------------------------------------------------------------------ #
    def execute_sync(self, prompt: str, **kwargs: Any) -> dict:
        """阻塞执行并返回汇总（含 run_id / session_id）。"""
        slot_sem, acquired, _limit = self._acquire_slot(
            str(kwargs.get("trigger") or "api"),
        )
        if not acquired:
            return {
                "run_id": None,
                "session_id": None,
                "finished": False,
                "error": "busy: 并发已达上限，本次跳过",
                "files": [],
                "answer": "",
                "skipped": True,
            }
        deadline = time.monotonic() + settings.schedule_run_timeout
        kwargs.setdefault("deadline", deadline)
        run_id: str | None = None
        session_id: str | None = None
        actual_mode: str | None = None
        answer_parts: list[str] = []
        files: list[str] = []
        error: str | None = None
        finished = False
        try:
            for event in self.execute_stream(prompt, acquire_slot=False, **kwargs):
                etype = event.get("type")
                if etype == "meta":
                    run_id = event.get("run_id")
                    session_id = event.get("session_id")
                    # 实际执行模式（会话模式不可变，可能与请求模式不同）
                    actual_mode = event.get("mode")
                elif etype == "model_text":
                    answer_parts.append(event.get("content", ""))
                elif etype == "files":
                    files = [f["name"] for f in event.get("files", [])]
                elif etype == "interrupted":
                    # S4：取消在工具边界生效 → 终态 interrupted（不是 failed）
                    final_status = "interrupted"
                    error = event.get("content") or "运行已被取消"
                elif etype == "error":
                    error = event.get("content")
                elif etype == "done":
                    finished = True
            return {
                "run_id": run_id,
                "session_id": session_id,
                "finished": finished,
                "files": files,
                "error": error,
                "answer": "".join(answer_parts)[-4000:],
                "model": kwargs.get("model") or settings.default_model,
                "prompt": prompt,
                # 实际执行的模式（不一定是请求的模式：会话模式不可变）
                "mode": actual_mode or kwargs.get("mode") or "work",
            }
        finally:
            if slot_sem is not None:
                slot_sem.release()

    # ------------------------------------------------------------------ #
    # Plan 审批恢复执行
    # ------------------------------------------------------------------ #
    def resume_after_approval(self, run_id: str) -> bool:
        """审批通过后在后台线程恢复执行（按计划注入）。"""
        run = self.run_service.get_run(run_id)
        if run is None or run.status != "queued":
            return False
        meta = dict(run.meta)
        prompt = meta.pop("prompt", "")
        plan = run.plan or []
        team_id = meta.pop("team_id", None)
        skills = meta.pop("skills", None)
        mode = meta.pop("mode", "work")
        session_id = run.session_id

        def _run() -> None:
            self.run_service.mark_running(run_id)
            buffer: list[dict] = []
            answer_parts: list[str] = []
            files: list[dict] = []
            steps: list[dict] = []
            error: str | None = None
            final_status = "success"
            try:
                team_meta = None
                resolved = skills
                if team_id and self.team_service is not None:
                    try:
                        resolved, team_meta, _ = self.team_service.resolve_for_agent(team_id, query=prompt, mode=mode)
                    except KeyError:
                        pass
                history = self.session_service.build_history(session_id) if session_id else []
                stream = self.agent_service.stream(
                    prompt,
                    meta.get("model"),
                    skills=resolved,
                    enable_mcp=bool(meta.get("enable_mcp")),
                    mcp_servers=meta.get("mcp_servers") or [],
                    enable_rag=bool(meta.get("enable_rag")),
                    enable_web_research=bool(meta.get("enable_web_research")),
                    enable_reflection=False,
                    mode=mode,
                    history=history,
                    team=team_meta,
                    plan=plan,
                    # P1-08：恢复段必须接入与主路径**同一份** steer / cancel hook，
                    # 否则审批通过后的那段执行既不能取消也不能转向
                    # （此前未传 → 恢复段完全不可干预）。
                    steer_hook=self._steer_hook(run_id),
                    cancel_hook=self._cancel_hook(run_id),
                    # **W2-02**：恢复段同样要归属（否则审批后的执行不计入成本）
                    run_id=run_id,
                    session_id=session_id,
                )
                last_flush = time.monotonic()
                for event in stream:
                    etype = event.get("type")
                    if etype == "model_text":
                        answer_parts.append(event.get("content", ""))
                    elif etype in ("tool_call", "tool_result"):
                        steps.append({"type": etype, **{k: v for k, v in event.items() if k != "type"}})
                    elif etype == "files":
                        files = event.get("files", [])
                    elif etype == "interrupted":
                        # P1-08：恢复段也支持取消 → 终态 interrupted（与主路径一致）
                        final_status = "interrupted"
                        error = event.get("content") or "运行已被取消"
                    elif etype == "error":
                        error = event.get("content")
                    buffer.append(event)
                    if len(buffer) >= EVENT_FLUSH_COUNT or time.monotonic() - last_flush > EVENT_FLUSH_INTERVAL:
                        self.run_service.append_events(run_id, list(buffer))
                        buffer.clear()
                        last_flush = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                logger.exception("审批恢复执行失败: %s", run_id)
                error = f"{type(exc).__name__}: {exc}"
            finally:
                if buffer:
                    self.run_service.append_events(run_id, list(buffer))

            answer = "".join(answer_parts)
            if session_id and answer:
                self.session_service.append_message(
                    session_id, "assistant", answer, run_id=run_id,
                    steps=steps[-20:], files=files, meta={"mode": mode, "approved": True},
                )
            self.run_service.finish(
                run_id,
                # P1-08：终态优先级同主路径 —— 显式终止原因（interrupted）> error
                ("failed" if error else "success")
                if final_status == "success"
                else final_status,
                summary=answer[:500] or (error or ""),
                files=files,
                error=error,
            )

        # P3-15：提交到**受控线程池**（非 daemon 线程）
        # **W2-04 / AUD2-H06（审批恢复段丢 contextvars）**
        # ``ThreadPoolExecutor`` 的工作线程**不会继承** contextvars
        # （每个线程有独立的顶层 Context）→ 恢复段里
        # ``unattended_context`` / ``dangerous_tools_context`` 回落为默认 ``False``
        # → 权限 ``ask`` **不再降级为 deny**，无人值守任务会**挂在等待人工审批**上
        # （最长 ``permission_approval_timeout=120s``），并可能被判失败触发退避；
        # 且任务行上的 ``allow_dangerous_tools`` 在恢复段失效，与首段行为不一致。
        #
        # 修复：显式 ``copy_context()`` 并用 ``ctx.run`` 在该上下文里执行。
        import contextvars as _cv

        _resume_ctx = _cv.copy_context()
        self._resume_pool.submit(_resume_ctx.run, _run)
        return True

    def resume_pending_approvals(self) -> int:
        """启动时扫描「已批准但未恢复」的 run 并重新执行（P3-15）。

        恢复参数写在 ``runs.meta_json``（含 ``resume_of``），因此
        **进程重启后仍能续跑**——此前用 daemon 线程，进程一退出执行就丢。
        """
        resumed = 0
        try:
            from app.services.run_service import RunService

            runs, _total = RunService().list_runs(status="queued", page=1, page_size=200)
        except Exception as exc:  # noqa: BLE001 - 恢复失败不应阻塞启动
            logger.warning("扫描待恢复 run 失败: %s", exc)
            return 0
        for run in runs:
            meta = dict(run.meta or {})
            if not meta.get("resume_of"):
                continue
            try:
                if self.resume_after_approval(run.id):
                    resumed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("恢复 run %s 失败: %s", run.id, exc)
        if resumed:
            logger.info("已恢复 %d 个待审批续跑的 run", resumed)
        return resumed

    def close(self, wait: bool = True) -> None:
        """优雅关闭：等待在跑的恢复任务完成（P3-15 验收②）。"""
        try:
            self._resume_pool.shutdown(wait=wait)
        except Exception as exc:  # noqa: BLE001
            logger.warning("恢复线程池关闭失败: %s", exc)

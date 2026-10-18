"""RunExecutor —— 「Agent 执行 + 落库」编排层。

- 供 HTTP（SSE / 阻塞）与定时任务复用；
- **DB Session 在生成器内部创建**（StreamingResponse 返回后 FastAPI 依赖已释放）；
- 事件批量入库；结束时写 assistant 消息 + 更新 run 状态；
- 客户端断开 → run 标记 interrupted；异常 → failed。
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    from app.services.agent_service import AgentService
    from app.services.run_service import RunService
    from app.services.session_service import SessionService
    from app.services.team_service import TeamService

logger = logging.getLogger(__name__)

EVENT_FLUSH_COUNT = 20
EVENT_FLUSH_INTERVAL = 2.0


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
        self._semaphore = threading.BoundedSemaphore(settings.schedule_max_concurrent)

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
        trigger: str = "api",
        task_id: str | None = None,
        scheduled_for: str | None = None,
        deadline: float | None = None,
        run_id: str | None = None,
    ) -> Iterator[dict]:
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
                yield {"type": "error", "content": f"团队不存在: {team_id}"}
                yield {"type": "done"}
                return

        # ---- 会话 ----
        session = None
        if session_id:
            session = self.session_service.get(session_id, message_limit=0)
            if session is None:
                yield {"type": "error", "content": f"会话不存在: {session_id}"}
                yield {"type": "done"}
                return
            mode = session.mode  # 会话模式不可变
            if plan_first and mode == "chat":
                yield {"type": "error", "content": "该会话是对话模式，不支持计划审批；请新建工作模式会话"}
                yield {"type": "done"}
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
                yield {"type": "notice", "content": "相同调度槽位已存在运行记录，跳过"}
                yield {"type": "done"}
                return
            run_id = run.id
        else:
            # 预创建 run（调度器幂等闸门）：补充 meta 便于审批恢复
            existing = self.run_service.get_run(run_id)
            if existing is None:
                yield {"type": "error", "content": f"运行记录不存在: {run_id}"}
                yield {"type": "done"}
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

        # ---- 执行 ----
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
                mode=mode,
                history=history,
                team=team_meta,
                plan_first=plan_first,
                deadline=deadline,
            )
            for event in stream:
                etype = event.get("type")
                if etype == "model_text":
                    answer_parts.append(event.get("content", ""))
                elif etype in ("tool_call", "tool_result", "plan", "reflection_plan"):
                    steps.append({"type": etype, **{k: v for k, v in event.items() if k != "type"}})
                elif etype == "files":
                    files = event.get("files", [])
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

        if error:
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
    # 阻塞执行（脚本 / 定时任务）
    # ------------------------------------------------------------------ #
    def execute_sync(self, prompt: str, **kwargs: Any) -> dict:
        """阻塞执行并返回汇总（含 run_id / session_id）。"""
        acquired = self._semaphore.acquire(blocking=False)
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
        answer_parts: list[str] = []
        files: list[str] = []
        error: str | None = None
        finished = False
        try:
            for event in self.execute_stream(prompt, **kwargs):
                etype = event.get("type")
                if etype == "meta":
                    run_id = event.get("run_id")
                    session_id = event.get("session_id")
                elif etype == "model_text":
                    answer_parts.append(event.get("content", ""))
                elif etype == "files":
                    files = [f["name"] for f in event.get("files", [])]
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
            }
        finally:
            self._semaphore.release()

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
                "failed" if error else "success",
                summary=answer[:500] or (error or ""),
                files=files,
                error=error,
            )

        thread = threading.Thread(target=_run, name=f"run-resume-{run_id[:8]}", daemon=True)
        thread.start()
        return True

"""多 Agent 编排服务（P2-09 路 B · P2-11 黑板接入 · P2-08 收费站）。

此前 ``TeamOrchestrator``（~350 行，支持 parallel / sequential / review 三模式）
**只被测试引用**——运行时零调用；文档却称「多 Agent 编排（3 模式）已落地」。
本模块把它接到**真实入口**，并补上三处配套能力：

- **主 Agent 作为 worker**（P2-09）：子任务由主 Agent 执行（``executor`` 闭包），
  不再依赖外部注入的假执行器；
- **黑板接入**（P2-11）：子任务登记为黑板任务项，状态随执行流转
  （pending → running → done / failed），依赖未完成的项由 ``recompute`` 自动
  置 blocked / ready——「依赖未完成的项不启动」这条验收标准由此真正生效；
- **收费站**（P2-08）：主上下文**只含压缩通知**，子任务原始推理不进主上下文，
  由 ``tollgate`` 校验。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.services.exec.team.blackboard import BlackboardService
from app.services.exec.team.messaging import MessageService, tollgate
from app.services.exec.team.orchestrator import (
    MODES,
    Executor,
    OrchestrationResult,
    SubTask,
    TeamOrchestrator,
    main_context_notifications,
)

logger = logging.getLogger(__name__)

__all__ = ["OrchestrationService", "MODES", "SubTask"]


class OrchestrationService:
    """把 ``TeamOrchestrator`` 接到真实执行链路。"""

    def __init__(
        self,
        agent_service: Any | None = None,
        *,
        message_service: MessageService | None = None,
        board_service: BlackboardService | None = None,
        max_workers: int = 4,
    ) -> None:
        self.agent_service = agent_service
        self.messages = message_service or MessageService()
        self.boards = board_service or BlackboardService()
        self.max_workers = max_workers

    # ------------------------------------------------------------------ #
    # 主 Agent 作为 worker
    # ------------------------------------------------------------------ #
    def _agent_executor(
        self,
        *,
        model: str | None,
        agent_mode: str = "work",
        skills: list[str] | None = None,
    ) -> Executor:
        """子任务执行器：**用主 Agent 跑子任务**（P2-09 路 B 的核心）。"""

        def _exec(task: SubTask, context: str) -> str:
            svc = self.agent_service
            if svc is None:
                raise RuntimeError("编排服务未绑定 Agent 服务，无法执行子任务")
            prompt = (task.prompt or task.title or "").strip()
            if not prompt:
                raise ValueError(f"子任务 {task.title!r} 缺少 prompt")
            if context:
                prompt = f"{prompt}\n\n【共享上下文】\n{context}"
            parts: list[str] = []
            for event in svc.stream(prompt, model, mode=agent_mode, skills=skills):
                if event.get("type") == "model_text":
                    parts.append(str(event.get("content") or ""))
            return "".join(parts)

        return _exec

    # ------------------------------------------------------------------ #
    # 黑板接入
    # ------------------------------------------------------------------ #
    def _register_board(
        self,
        board_id: str,
        tasks: list[SubTask],
    ) -> tuple[dict[int, int], dict[str, int]]:
        """把子任务登记为黑板项。

        :return: ``(下标 → 黑板项 id, 标题 → 黑板项 id)``
        """
        id_by_index: dict[int, int] = {}
        id_by_title: dict[str, int] = {}
        for idx, st in enumerate(tasks):
            item = self.boards.create_item(
                board_id,
                st.title,
                detail=st.prompt,
                assignee=st.assignee or (st.role or None),
            )
            id_by_index[idx] = item.id
            id_by_title[st.title] = item.id
        # 依赖：创建**之后**再挂——黑板项 id 是自增的，创建时还拿不到同伴的 id
        for idx, st in enumerate(tasks):
            for dep_idx in st.deps:
                dep_id = id_by_index.get(dep_idx)
                if dep_id is None:
                    continue
                try:
                    self.boards.add_dep(id_by_index[idx], dep_id)
                except Exception as exc:  # noqa: BLE001 - 成环等由黑板拒绝
                    logger.warning("黑板依赖挂载失败: %s", exc)
        return id_by_index, id_by_title

    def _tracked_executor(
        self,
        executor: Executor,
        id_by_title: dict[str, int],
    ) -> Executor:
        """包一层：**黑板状态随执行流转**（P2-11）。"""

        def _exec(task: SubTask, context: str) -> str:
            item_id = id_by_title.get(task.title)
            if item_id is not None:
                try:
                    self.boards.set_status(item_id, "running")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("黑板状态置 running 失败: %s", exc)
            try:
                output = executor(task, context)
            except Exception:
                if item_id is not None:
                    try:
                        self.boards.set_status(item_id, "failed")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("黑板状态置 failed 失败: %s", exc)
                raise
            if item_id is not None:
                try:
                    self.boards.complete(item_id, {"output": output[:2000]})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("黑板任务项完成落账失败: %s", exc)
            return output

        return _exec

    # ------------------------------------------------------------------ #
    # 入口
    # ------------------------------------------------------------------ #
    def orchestrate(
        self,
        *,
        task: str,
        subtasks: list[dict] | list[SubTask],
        mode: str = "parallel",
        board_id: str | None = None,
        reviewer: str = "reviewer",
        model: str | None = None,
        agent_mode: str = "work",
        skills: list[str] | None = None,
        executor: Executor | None = None,
    ) -> dict:
        """执行一次多 Agent 编排。

        :param subtasks: 子任务列表；每项支持 ``title`` / ``prompt`` / ``role`` /
            ``assignee`` / ``deps``（**deps 用子任务下标**）。
        :param board_id: 提供时，子任务登记为黑板任务项并随执行流转。
        :param executor: 自定义执行器（测试用）；缺省用**主 Agent**。
        """
        if mode not in MODES:
            raise ValueError(f"mode 必须是 {'/'.join(MODES)}")

        tasks: list[SubTask] = []
        for raw in subtasks or []:
            if isinstance(raw, SubTask):
                tasks.append(raw)
                continue
            if not isinstance(raw, dict):
                raise ValueError("子任务必须是对象")
            title = str(raw.get("title") or "").strip()
            if not title:
                raise ValueError("子任务缺少 title")
            tasks.append(SubTask(
                title=title,
                prompt=str(raw.get("prompt") or title),
                role=str(raw.get("role") or ""),
                assignee=(str(raw["assignee"]) if raw.get("assignee") else None),
                deps=[int(d) for d in (raw.get("deps") or [])],
            ))
        if not tasks:
            raise ValueError("至少需要一个子任务")

        id_by_title: dict[str, int] = {}
        if board_id:
            _id_by_index, id_by_title = self._register_board(board_id, tasks)

        base_executor = executor or self._agent_executor(
            model=model, agent_mode=agent_mode, skills=skills,
        )
        tracked = self._tracked_executor(base_executor, id_by_title) if id_by_title else base_executor

        orchestrator = TeamOrchestrator(
            tracked,
            message_service=self.messages,
            max_workers=self.max_workers,
        )
        result: OrchestrationResult = orchestrator.run(
            tasks, mode=mode, board_id=board_id, reviewer=reviewer,
        )

        # P2-08 收费站：主上下文**只含压缩通知**
        main_context = main_context_notifications(result)
        gate = tollgate(main_context)

        board_items: list[dict] = []
        if board_id:
            try:
                board_items = [i.as_dict() for i in self.boards.recompute(board_id)]
            except Exception as exc:  # noqa: BLE001
                logger.warning("黑板重算失败: %s", exc)

        return {
            "mode": mode,
            "task": task,
            "summary": result.summary,
            "results": [r.as_dict() for r in result.results],
            "notifications": [n.as_dict() for n in result.notifications],
            # 主上下文只含压缩通知（子任务原始推理不进主上下文）
            "main_context": main_context,
            "tollgate": {"ok": gate["ok"], "violations": gate["violations"]},
            "board_id": board_id,
            "board_items": board_items,
        }

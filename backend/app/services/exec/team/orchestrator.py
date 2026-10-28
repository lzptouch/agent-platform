"""多 Agent 编排（S6 / WP-6.3）。

三种编排：
- ``parallel``：子任务并行 → 汇总；
- ``sequential``：前序产出作为后序输入；
- ``review``：执行者产出 → 评审者修订 → 汇总。

编排器只负责**流程与汇总**，具体执行交给注入的 ``executor``（便于单测）。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from app.services.exec.team.messaging import AgentMessage, MessageService, build_main_context_block

logger = logging.getLogger(__name__)

MODES = ("parallel", "sequential", "review")


@dataclass
class SubTask:
    """一个子任务。"""

    title: str
    prompt: str
    role: str = ""
    assignee: str | None = None
    deps: list[int] = field(default_factory=list)


@dataclass
class SubResult:
    """子任务结果。"""

    title: str
    role: str
    output: str
    error: str | None = None

    def as_dict(self) -> dict:
        return {"title": self.title, "role": self.role, "output": self.output, "error": self.error}


@dataclass
class OrchestrationResult:
    """编排结果（含汇总）。"""

    mode: str
    results: list[SubResult] = field(default_factory=list)
    summary: str = ""
    notifications: list[AgentMessage] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "results": [r.as_dict() for r in self.results],
            "summary": self.summary,
            "notifications": [n.as_dict() for n in self.notifications],
        }


#: 执行器签名：``(task: SubTask, context: str) -> str``
Executor = Callable[[SubTask, str], str]


class TeamOrchestrator:
    """多 Agent 编排器。"""

    def __init__(
        self,
        executor: Executor,
        *,
        message_service: MessageService | None = None,
        max_workers: int = 4,
    ) -> None:
        self.executor = executor
        self.messages = message_service or MessageService()
        self.max_workers = max_workers

    # ------------------------------------------------------------------ #
    # 入口
    # ------------------------------------------------------------------ #
    def run(
        self,
        tasks: list[SubTask],
        *,
        mode: str = "parallel",
        board_id: str | None = None,
        reviewer: str = "reviewer",
    ) -> OrchestrationResult:
        if mode not in MODES:
            raise ValueError(f"mode 必须是 {'/'.join(MODES)}")
        if not tasks:
            return OrchestrationResult(mode=mode, summary="（无子任务）")

        if mode == "parallel":
            results = self._run_parallel(tasks)
        elif mode == "sequential":
            results = self._run_sequential(tasks)
        else:
            results = self._run_review(tasks, reviewer=reviewer)

        # 子任务产出 → **压缩通知**（主上下文只含通知，不含原文）
        notifications: list[AgentMessage] = []
        for r in results:
            try:
                notifications.append(self.messages.notify(
                    f"{r.title} 完成：{r.output[:200]}",
                    board_id=board_id,
                    from_role=r.role,
                    refs=[{"type": "message", "id": r.title, "role": r.role}],
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("通知写入失败: %s", exc)

        summary = self._summarize(results)
        return OrchestrationResult(mode=mode, results=results, summary=summary,
                                   notifications=notifications)

    # ------------------------------------------------------------------ #
    # 三种编排
    # ------------------------------------------------------------------ #
    def _run_parallel(self, tasks: list[SubTask]) -> list[SubResult]:
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(tasks)))) as pool:
            futures = [pool.submit(self._execute, t, "") for t in tasks]
            return [f.result() for f in futures]

    def _run_sequential(self, tasks: list[SubTask]) -> list[SubResult]:
        results: list[SubResult] = []
        context = ""
        for task in tasks:
            res = self._execute(task, context)
            results.append(res)
            context = res.output  # 前序产出作为后序输入
        return results

    def _run_review(self, tasks: list[SubTask], *, reviewer: str) -> list[SubResult]:
        results = self._run_parallel(tasks)
        merged = "\n".join(f"## {r.title}\n{r.output}" for r in results)
        review_task = SubTask(
            title="评审修订",
            prompt=f"请评审并修订以下产出：\n{merged}",
            role=reviewer,
        )
        review = self._execute(review_task, merged)
        results.append(review)
        return results

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _execute(self, task: SubTask, context: str) -> SubResult:
        try:
            output = self.executor(task, context)
            return SubResult(title=task.title, role=task.role, output=str(output))
        except Exception as exc:  # noqa: BLE001 —— 子任务失败不拖垮整体
            logger.warning("子任务失败: %s", exc)
            return SubResult(title=task.title, role=task.role, output="", error=str(exc))

    @staticmethod
    def _summarize(results: list[SubResult]) -> str:
        ok = [r for r in results if not r.error]
        failed = [r for r in results if r.error]
        lines = [f"完成 {len(ok)}/{len(results)} 个子任务"]
        for r in results:
            status = "失败" if r.error else "完成"
            first = (r.output or r.error or "").strip().splitlines()
            head = first[0][:120] if first else ""
            lines.append(f"- [{status}] {r.title}（{r.role}）：{head}")
        return "\n".join(lines)


def main_context_notifications(result: OrchestrationResult) -> str:
    """主上下文里关于子任务的**唯一**内容（压缩通知块）。"""
    return build_main_context_block(result.notifications)

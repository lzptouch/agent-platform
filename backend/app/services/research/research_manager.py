"""ResearchManager —— 深度研究任务的生命周期管理。

自 ``deep_research/app/main.py`` 的 ``TaskManager`` 迁移并增强：
- **JSON 持久化**：原版仅内存 dict，重启即丢；新版落盘到 ``data/research/tasks.json``
- **报告落盘**：``data/research/<task_id>/report_*.md`` + ``meta_*.json``
- **线程池并发**：``ThreadPoolExecutor(max_workers=settings.research_max_concurrent)``
- **优雅关闭**：``shutdown()`` 供 FastAPI lifespan 调用
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.research.research_config import AGENT_CONFIG, OUTPUT_CONFIG

logger = logging.getLogger(__name__)

# 任务终态
TERMINAL_STATES = {"completed", "failed"}


class ResearchManager:
    """管理所有深度研究任务。"""

    def __init__(self, persist: bool | None = None) -> None:
        self.output_dir: Path = Path(settings.research_output_abs)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.persist: bool = settings.research_persist if persist is None else persist
        self.tasks: dict[str, dict[str, Any]] = {}
        self.executor = ThreadPoolExecutor(max_workers=settings.research_max_concurrent)
        self._lock = threading.Lock()
        self._load_tasks()

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #
    @property
    def _tasks_file(self) -> Path:
        return self.output_dir / "tasks.json"

    def _load_tasks(self) -> None:
        """启动时恢复历史任务（运行中的任务标记为中断）。"""
        if not self.persist or not self._tasks_file.exists():
            return
        try:
            data = json.loads(self._tasks_file.read_text(encoding="utf-8"))
            for task in data.get("tasks", []):
                if task.get("status") not in TERMINAL_STATES:
                    task["status"] = "failed"
                    task["error"] = task.get("error") or "服务重启，任务已中断"
                self.tasks[task["task_id"]] = task
            logger.info("已恢复 %d 个研究任务记录", len(self.tasks))
        except Exception as exc:  # noqa: BLE001 —— 持久化损坏不应阻塞启动
            logger.warning("研究任务记录恢复失败: %s", exc)

    def _save_tasks(self) -> None:
        if not self.persist:
            return
        try:
            with self._lock:
                payload = {"tasks": list(self.tasks.values()), "updated_at": datetime.now(timezone.utc).isoformat()}
                self._tasks_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
        except OSError as exc:
            logger.warning("研究任务记录落盘失败: %s", exc)

    # ------------------------------------------------------------------ #
    # 任务 CRUD
    # ------------------------------------------------------------------ #
    def create_task(
        self,
        task_text: str,
        *,
        max_workers: int | None = None,
        max_iterations: int | None = None,
        quality_threshold: int | None = None,
    ) -> str:
        """创建新任务并返回 task_id。"""
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "task_id": task_id,
            "original_task": task_text,
            "status": "pending",
            "progress": [],
            "progress_summary": {},
            "config": {
                "max_workers": max_workers or AGENT_CONFIG["max_workers"],
                "max_iterations": max_iterations or AGENT_CONFIG["max_iterations"],
                "quality_threshold": quality_threshold or AGENT_CONFIG["quality_threshold"],
            },
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        self._save_tasks()
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        return [
            {
                "task_id": t["task_id"],
                "original_task": t["original_task"][:50] + "..." if len(t["original_task"]) > 50 else t["original_task"],
                "status": t["status"],
                "created_at": t["created_at"],
                "quality_score": t["result"]["quality_score"] if t.get("result") else None,
            }
            for t in sorted(self.tasks.values(), key=lambda x: x["created_at"], reverse=True)
        ]

    def delete_task(self, task_id: str) -> bool:
        """删除任务（仅允许删除已结束的任务）。"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task["status"] not in TERMINAL_STATES:
            raise ValueError("任务正在运行中，无法删除")
        self.tasks.pop(task_id, None)
        self._save_tasks()
        return True

    def running_count(self) -> int:
        return sum(1 for t in self.tasks.values() if t["status"] == "running")

    # ------------------------------------------------------------------ #
    # 状态流转
    # ------------------------------------------------------------------ #
    def update_progress(self, task_id: str, stage: str, data: dict) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        event = {"stage": stage, "data": data, "timestamp": datetime.now().isoformat()}
        task["progress"].append(event)
        task["progress_summary"] = {
            "current_stage": stage,
            "last_update": event["timestamp"],
            **(data or {}),
        }

    def set_running(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task:
            task["status"] = "running"
            task["started_at"] = datetime.now().isoformat()
            self._save_tasks()

    def set_completed(self, task_id: str, state) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        task["status"] = "completed"
        task["completed_at"] = datetime.now().isoformat()
        task["result"] = {
            "report": state.final_report,
            "quality_score": state.quality_score,
            "iteration_count": state.iteration_count,
            "duration": state.end_time - state.start_time,
        }
        self._save_report(task_id, state)
        self._save_tasks()

    def set_failed(self, task_id: str, error: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        task["status"] = "failed"
        task["completed_at"] = datetime.now().isoformat()
        task["error"] = error
        self._save_tasks()

    # ------------------------------------------------------------------ #
    # 报告落盘
    # ------------------------------------------------------------------ #
    def _save_report(self, task_id: str, state) -> None:
        """保存 Markdown 报告 + JSON 元数据。"""
        try:
            task_dir = self.output_dir / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            (task_dir / f"report_{timestamp}.md").write_text(state.final_report, encoding="utf-8")

            plan = state.task_plan
            meta = {
                "task_id": task_id,
                "original_task": state.original_task,
                "status": state.status,
                "quality_score": state.quality_score,
                "duration": state.end_time - state.start_time,
                "timestamp": timestamp,
                "task_plan": {
                    "understanding": plan.task_understanding if plan else {},
                    "subtask_count": len(plan.subtasks) if plan else 0,
                    "report_structure": plan.report_structure if plan else {},
                },
                "worker_results_count": len(state.worker_results),
                "iteration_count": state.iteration_count,
                "iteration_history": [
                    {
                        "iteration": r.iteration,
                        "quality_score": r.quality_score,
                        "report_length": len(r.report),
                        "gap_count": len(r.gap_analysis.get("missing_aspects", [])) if r.gap_analysis else 0,
                        "supplementary_task_count": len(r.supplementary_results),
                    }
                    for r in state.iteration_history
                ],
                "search_provider": _search_provider(),
            }
            (task_dir / f"meta_{timestamp}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            logger.info("研究报告已保存: %s", task_dir)
        except OSError as exc:
            logger.warning("研究报告落盘失败: %s", exc)

    # ------------------------------------------------------------------ #
    # 资源释放
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """关闭线程池（不等待未完成任务）。"""
        self.executor.shutdown(wait=False)
        self._save_tasks()
        logger.info("ResearchManager 已关闭")


def _search_provider() -> str:
    try:
        from app.services.research.search_client import get_search_client

        return get_search_client().provider
    except Exception:  # noqa: BLE001
        return "unknown"


# 供 deep_research 兼容：输出目录常量
OUTPUT_CONFIG["output_dir"] = settings.research_output_abs

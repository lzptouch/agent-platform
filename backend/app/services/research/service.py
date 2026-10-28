"""Research 链路核心服务（自 ``deep_research/app/agent/research_agent.py`` 迁移）。

**已移除**（按整合计划）：
- ``ConsoleReporter``：终端着色输出（约 180 行）—— API 场景由 SSE 事件承担
- ``main()`` CLI 入口（约 70 行）—— 需要时用 ``scripts/research_cli.py`` 重新提供

**保留**：``run_research()`` 编排入口 + 临时覆盖 ``AGENT_CONFIG`` 的语义。
"""
from __future__ import annotations

import logging
from typing import Callable

from app.services.research.orchestrator import Orchestrator, ResearchState
from app.services.research.research_config import AGENT_CONFIG
from app.services.research.workers import search_worker_factory

logger = logging.getLogger(__name__)

# 允许按任务临时覆盖的配置项（其余保持全局默认）
OVERRIDABLE_KEYS = ("max_iterations", "quality_threshold")


def run_research(
    task: str,
    *,
    max_workers: int | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    config_overrides: dict | None = None,
) -> ResearchState:
    """执行一次深度研究，返回最终 ``ResearchState``。

    参数:
        task: 研究任务描述
        max_workers: 最大并行 Worker 数
        on_progress: 进度回调 ``(stage, data)``
        config_overrides: 临时覆盖 ``AGENT_CONFIG`` 的项（仅 ``max_iterations`` /
            ``quality_threshold``），执行完在 ``finally`` 中还原，避免并发串扰。

    返回:
        ResearchState: 含 ``final_report`` / ``quality_score`` / ``status`` 等
    """
    overrides = {
        k: v for k, v in (config_overrides or {}).items() if k in OVERRIDABLE_KEYS and v is not None
    }
    # 覆盖按实例传递，不再「改全局 → finally 还原」：
    # 后者不是并发安全的（两个研究任务会互相覆盖同一份全局 dict）。
    orchestrator = Orchestrator(
        worker_factory=search_worker_factory,
        max_workers=max_workers or AGENT_CONFIG["max_workers"],
        on_progress=on_progress,
        overrides=overrides,
    )
    return orchestrator.run(task)

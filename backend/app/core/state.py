"""应用状态（共享服务）初始化。

既在 ``lifespan`` 启动时调用，也在依赖注入时惰性兜底，
保证即使没有触发 startup 事件（例如直接 ``TestClient(app)``）也能工作。
"""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI

from app.core.config import settings
from app.services.agent_service import AgentService
from app.services.code_executor import LocalCodeExecutor
from app.services.desktop_service import DesktopService
from app.services.mcp_manager import get_mcp_manager
from app.services.security.permissions import PermissionService
from app.services.research.research_manager import ResearchManager
from app.services.run_executor import RunExecutor
from app.services.run_service import RunService
from app.services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)
from app.services.session_service import SessionService
from app.services.skill_manager import SkillManager
from app.services.team_service import TeamService
from app.services.tool_registry import ToolRegistry


_init_lock = threading.Lock()


def init_app_state(app: FastAPI, force: bool = False) -> None:
    """初始化（或复用）应用级共享服务树。

    **AUD2-M24 / W9-14（check-then-set 非原子）修复**

    此前 ``if not force and getattr(app.state, "initialized", False): return`` 是
    典型的 **check-then-act**：``app/api/deps.py`` 的**每个**依赖都会调用本函数，
    两个并发首请求可同时通过检查 → **各自创建一整套服务树** →
    第二个实例的 ``SchedulerService`` 会再起一个 ``BackgroundScheduler``（多调度器，
    同一任务被触发两次），且 ``resume_pending_approvals()`` 被跑两次 →
    **同一个 run 被恢复执行两次**。

    修复：加锁 + 双重检查。
    """
    with _init_lock:
        if not force and getattr(app.state, "initialized", False):
            return
        _init_app_state_locked(app, force=force)


def _init_app_state_locked(app: FastAPI, force: bool = False) -> None:

    settings.ensure_dirs()

    skill_manager = SkillManager(settings.skills_dir, settings.custom_skills_dir)
    executor = LocalCodeExecutor()
    # P2-01：进程级单例（常驻 MCP 会话池必须全局唯一）
    mcp_manager = get_mcp_manager()
    tool_registry = ToolRegistry(mcp_manager)
    research_manager = ResearchManager()
    session_service = SessionService()
    run_service = RunService()
    team_service = TeamService(skill_manager)
    agent_service = AgentService(skill_manager, executor, mcp_manager, tool_registry)
    run_executor = RunExecutor(agent_service, session_service, run_service, team_service)
    scheduler_service = SchedulerService(run_executor)
    desktop_service = DesktopService()
    # P2-15：全仓唯一的 PermissionService（引擎单例）——
    # 兼容层已删除，权限判定与规则读写只有这一个落点。
    permission_service = PermissionService.instance()
    # P2-09 路 B：多 Agent 编排服务（主 Agent 作为 worker + 黑板接入 + 收费站）
    # **延迟导入**：顶层 import 会形成循环（app.main → api.v1.router → api.deps →
    # core.state → exec.team.service → …），导致 api_router 在被 include 时**尚未填充**
    # → app 上一个 /api/v1 路由都没挂上。
    from app.services.exec.team.service import OrchestrationService

    orchestration_service = OrchestrationService(agent_service)

    # P1-03：启动时**收敛内置权限规则**（去重 + 补齐，幂等）。
    # 内置规则此前被 0002 与 0004 两个迁移各写一遍，而 SQLite 唯一约束
    # (scope, pattern, workspace_id) 对 workspace_id IS NULL 不去重
    # → 新装库上 8 条规则出现两次。这里统一收敛一次（重复启动无副作用）。
    try:
        from app.services.security.permissions import PermissionService as PermissionEngine

        stats = PermissionEngine.instance().ensure_builtin_rules()
        if stats.get("removed") or stats.get("added"):
            logger.info(
                "内置权限规则已收敛：删除重复 %s 条，补齐 %s 条",
                stats.get("removed", 0), stats.get("added", 0),
            )
    except Exception:  # noqa: BLE001 - 规则收敛失败不应阻断启动
        logger.exception("内置权限规则收敛失败（继续启动）")

    app.state.skill_manager = skill_manager
    app.state.executor = executor
    app.state.mcp_manager = mcp_manager
    app.state.tool_registry = tool_registry
    app.state.research_manager = research_manager

    # P3-06：启动时**续跑**带 checkpoint 的中断研究任务
    try:
        research_manager.resume_interrupted()
    except Exception as exc:  # noqa: BLE001 - 续跑失败不应阻塞启动
        logger.warning("续跑中断研究任务失败: %s", exc)
    app.state.session_service = session_service
    app.state.run_service = run_service
    app.state.team_service = team_service
    app.state.run_executor = run_executor

    # P3-15：启动时扫描「已批准但未恢复」的 run 并续跑
    # （恢复参数写在 runs.meta_json，进程重启不丢）。
    try:
        run_executor.resume_pending_approvals()
    except Exception as exc:  # noqa: BLE001 - 恢复失败不应阻塞启动
        logger.warning("启动时恢复待审批 run 失败: %s", exc)
    app.state.scheduler_service = scheduler_service
    app.state.agent_service = agent_service
    app.state.desktop_service = desktop_service
    app.state.permission_service = permission_service
    app.state.orchestration_service = orchestration_service
    app.state.initialized = True

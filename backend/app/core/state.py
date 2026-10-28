"""应用状态（共享服务）初始化。

既在 ``lifespan`` 启动时调用，也在依赖注入时惰性兜底，
保证即使没有触发 startup 事件（例如直接 ``TestClient(app)``）也能工作。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import settings
from app.services.agent_service import AgentService
from app.services.code_executor import LocalCodeExecutor
from app.services.desktop_service import DesktopService
from app.services.mcp_manager import MCPManager
from app.services.permissions import PermissionService
from app.services.research.research_manager import ResearchManager
from app.services.run_executor import RunExecutor
from app.services.run_service import RunService
from app.services.scheduler_service import SchedulerService
from app.services.session_service import SessionService
from app.services.skill_manager import SkillManager
from app.services.team_service import TeamService
from app.services.tool_registry import ToolRegistry


def init_app_state(app: FastAPI, force: bool = False) -> None:
    if not force and getattr(app.state, "initialized", False):
        return

    settings.ensure_dirs()

    skill_manager = SkillManager(settings.skills_dir, settings.custom_skills_dir)
    executor = LocalCodeExecutor()
    mcp_manager = MCPManager()
    tool_registry = ToolRegistry(mcp_manager)
    research_manager = ResearchManager()
    session_service = SessionService()
    run_service = RunService()
    team_service = TeamService(skill_manager)
    agent_service = AgentService(skill_manager, executor, mcp_manager, tool_registry)
    run_executor = RunExecutor(agent_service, session_service, run_service, team_service)
    scheduler_service = SchedulerService(run_executor)
    desktop_service = DesktopService()
    permission_service = PermissionService()

    app.state.skill_manager = skill_manager
    app.state.executor = executor
    app.state.mcp_manager = mcp_manager
    app.state.tool_registry = tool_registry
    app.state.research_manager = research_manager
    app.state.session_service = session_service
    app.state.run_service = run_service
    app.state.team_service = team_service
    app.state.run_executor = run_executor
    app.state.scheduler_service = scheduler_service
    app.state.agent_service = agent_service
    app.state.desktop_service = desktop_service
    app.state.permission_service = permission_service
    app.state.initialized = True

"""依赖注入：从 ``app.state`` 取出共享服务实例。"""

from fastapi import Request

from app.core.state import init_app_state
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


def get_skill_manager(request: Request) -> SkillManager:
    init_app_state(request.app)
    return request.app.state.skill_manager


def get_executor(request: Request) -> LocalCodeExecutor:
    init_app_state(request.app)
    return request.app.state.executor


def get_agent_service(request: Request) -> AgentService:
    init_app_state(request.app)
    return request.app.state.agent_service


def get_mcp_manager(request: Request) -> MCPManager:
    init_app_state(request.app)
    return request.app.state.mcp_manager


def get_tool_registry(request: Request) -> ToolRegistry:
    init_app_state(request.app)
    return request.app.state.tool_registry


def get_research_manager(request: Request) -> ResearchManager:
    init_app_state(request.app)
    return request.app.state.research_manager


def get_session_service(request: Request) -> SessionService:
    init_app_state(request.app)
    return request.app.state.session_service


def get_run_service(request: Request) -> RunService:
    init_app_state(request.app)
    return request.app.state.run_service


def get_team_service(request: Request) -> TeamService:
    init_app_state(request.app)
    return request.app.state.team_service


def get_run_executor(request: Request) -> RunExecutor:
    init_app_state(request.app)
    return request.app.state.run_executor


def get_scheduler_service(request: Request) -> SchedulerService:
    init_app_state(request.app)
    return request.app.state.scheduler_service


def get_desktop_service(request: Request) -> DesktopService:
    init_app_state(request.app)
    return request.app.state.desktop_service


def get_permission_service(request: Request) -> PermissionService:
    init_app_state(request.app)
    return request.app.state.permission_service

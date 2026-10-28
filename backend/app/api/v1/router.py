"""聚合 v1 路由。"""

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    context,
    desktop,
    extensions,
    files,
    mcp_servers,
    permissions,
    rag,
    research,
    runs,
    schedules,
    sessions,
    skills,
    system,
    teams,
    web_research,
    workspace,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(skills.router)
api_router.include_router(agent.router)
api_router.include_router(sessions.router)
api_router.include_router(runs.router)
api_router.include_router(teams.router)
api_router.include_router(schedules.router)
api_router.include_router(files.router)
api_router.include_router(mcp_servers.router)
api_router.include_router(permissions.router)
api_router.include_router(workspace.router)
api_router.include_router(context.router)
api_router.include_router(extensions.router)
api_router.include_router(rag.router)
api_router.include_router(web_research.router)
api_router.include_router(research.router)
api_router.include_router(desktop.router)

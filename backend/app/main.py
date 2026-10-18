"""FastAPI 应用入口（纯后端 API 服务）。

启动方式：
    uvicorn app.main:app --reload --port 8000

前端为独立的 Vue 工程（../frontend/web/vue-element-plus）：
- 开发模式：`cd ../frontend/web/vue-element-plus && npm run dev`（Vite 代理 /api → 本服务）
- 生产模式：`node ../frontend/scripts/build-frontend.mjs` 后，本服务自动托管 ../frontend/dist
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import PROJECT_ROOT, settings
from app.core.state import init_app_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("agent-platform")

# 前端生产构建产物目录（apps/agent-platform/frontend/dist）
FRONTEND_DIST = PROJECT_ROOT.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """迁移数据库 → 初始化共享服务 → 启动调度器。"""
    # 1. 数据库迁移（失败即中止，不静默降级）
    from scripts.migrate import main as run_migrations

    try:
        run_migrations()
    except Exception:
        logger.exception("数据库迁移失败，启动中止")
        raise

    # 2. 共享服务
    init_app_state(app, force=True)

    skill_manager = app.state.skill_manager
    sync_result = skill_manager.sync_to_db()
    if sync_result.get("warnings"):
        logger.warning("Skill 同步告警: %s", sync_result["warnings"])
    logger.info("已加载 %d 个 Skill: %s", len(skill_manager.list_skills()),
                ", ".join(s["name"] for s in skill_manager.list_skills()) or "(无)")
    logger.info("输出目录: %s", settings.output_dir)
    logger.info("数据库: %s", settings.database_url_abs)
    if not settings.has_api_key:
        logger.warning("未配置 DASHSCOPE_API_KEY —— /api/v1/agent/run 将返回错误提示")
    if not settings.research_configured:
        logger.warning("未配置 BOCHA_API_KEY / SERPER_API_KEY —— /api/v1/research 检索将失败")

    # 3. 定时任务调度器（未获得租约时以 standby 运行）
    app.state.scheduler_service.start()

    if FRONTEND_DIST.exists():
        logger.info("检测到前端构建产物，托管于 / : %s", FRONTEND_DIST)
    yield
    app.state.scheduler_service.shutdown()
    app.state.research_manager.shutdown()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="统一 Agent 平台后端：Skill + MCP + RAG + Web Research 四链路。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/docs-info", include_in_schema=False)
def docs_info() -> dict:
    return {
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "health": "/api/v1/health",
        "ui": "/" if FRONTEND_DIST.exists() else "frontend dev server (npm run dev)",
    }


# ---------- 生产模式：托管前端构建产物 ----------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """SPA 路由回退：非 /api 路径一律返回 index.html；/api 未匹配路径保持 404。"""
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"API 路径不存在: /{full_path}")
        target = FRONTEND_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/v1/health",
            "frontend": "cd ../frontend/web/vue-element-plus && npm run dev（或 node ../frontend/scripts/build-frontend.mjs 后由本服务托管）",
        }

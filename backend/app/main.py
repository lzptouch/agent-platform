"""FastAPI 应用入口（纯后端 API 服务）。

启动方式：
    uvicorn app.main:app --reload --port 8000

前端为独立的 Vue 工程（../frontend/web/vue-element-plus）：
- 开发模式：`cd ../frontend/web/vue-element-plus && npm run dev`（Vite 代理 /api → 本服务）
- 生产模式：`node ../frontend/scripts/build-frontend.mjs` 后，本服务自动托管 ../frontend/dist
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import PROJECT_ROOT, settings
from app.core.errors import (
    REQUEST_ID_HEADER,
    AppError,
    ErrorCode,
    error_response,
    http_exception_response,
    set_request_id,
)
from app.core.state import init_app_state
from app.core.logging import bind_context, enable_file_logging, reset_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("agent")

# 前端生产构建产物目录（桌面态由壳通过 AGENT_FRONTEND_DIST 注入）
FRONTEND_DIST = settings.frontend_dist_dir


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

    # 2. 日志落盘（批次 03 / WP-3.2）：JSON 行 + 轮转；失败不阻断启动
    #    必须在迁移**之后**：alembic 的 env.py 会 fileConfig() 重置 root 的 handler，
    #    提前挂载会被它清掉（表现为「日志文件有启动几行、之后全没了」）。
    file_handler = enable_file_logging()
    if file_handler is not None:
        logger.info("日志落盘已启用: %s", file_handler.baseFilename)

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
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)

# ---------- 请求 ID 与统一错误体（S1 / WP-1.1） ----------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """生成/透传请求 ID，写入上下文并回写到响应头。"""
    rid = set_request_id(request.headers.get(REQUEST_ID_HEADER))
    # 日志上下文：让落盘日志能按 request_id 检索（批次 03 / WP-3.2）
    ctx_token = bind_context(request_id=rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        # 每个请求留一行可检索的落盘记录（request_id / 路径 / 状态 / 耗时）
        # 注意：必须在 finally 复位**之前**记录，否则 request_id 已经不在上下文里
        logger.info(
            "request %s %s -> %s (%.1fms)",
            request.method, request.url.path, response.status_code,
            (time.perf_counter() - started) * 1000,
        )
    except AppError as exc:
        return error_response(exc.status_code, exc.code, exc.message, detail=exc.detail)
    except HTTPException as exc:
        return http_exception_response(exc)
    finally:
        reset_context(ctx_token)
    response.headers[REQUEST_ID_HEADER] = rid
    return response


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError):  # type: ignore[no-untyped-def]
    return error_response(exc.status_code, exc.code, exc.message, detail=exc.detail)


@app.exception_handler(HTTPException)
async def _http_error_handler(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
    return http_exception_response(exc)


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
    logger.exception("未处理异常: %s", exc)
    return error_response(500, ErrorCode.INTERNAL, "服务内部错误")


app.include_router(api_router, prefix="/api/v1")


# ---------- 桌面模式：会话守卫与引导端点 ----------
if settings.desktop_mode:
    from app.desktop.bootstrap import bootstrap_response, guard

    @app.middleware("http")
    async def desktop_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        """桌面模式下校验 Host 白名单与会话令牌。"""
        path = request.url.path
        if path.startswith("/api/v1/"):
            try:
                guard(request)
            except HTTPException as exc:
                # 中间件内抛出的 HTTPException 不会经过异常处理器，必须显式转换
                return http_exception_response(exc)
        return await call_next(request)

    @app.get("/__desktop/bootstrap", include_in_schema=False)
    def desktop_bootstrap(request: Request):  # type: ignore[no-untyped-def]
        """一次性引导：校验 nonce → 下发 HttpOnly Cookie → 302 回首页。"""
        return bootstrap_response(request)

    @app.get("/__desktop/ping", include_in_schema=False)
    def desktop_ping() -> dict:
        """免鉴权存活探针（只回 ok，不泄露任何信息）。"""
        return {"ok": True}


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

"""FastAPI 应用入口（纯后端 API 服务）。

启动方式：
    uvicorn app.main:app --reload --port 8000

前端为独立的 Vue 工程（../frontend/web/vue-element-plus）：
- 开发模式：`cd ../frontend/web/vue-element-plus && npm run dev`（Vite 代理 /api → 本服务）
- 生产模式：`node ../frontend/scripts/build-frontend.mjs` 后，本服务自动托管 ../frontend/dist
"""

from __future__ import annotations

import hmac
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
    # P1-01：Web 形态最小鉴权——未配置时**显式告警**（不默认开启，避免打断单机用户）
    if not settings.desktop_mode and not settings.agent_api_key:
        logger.warning(
            "Web 形态未启用鉴权 —— 未配置 AGENT_API_KEY，/api/v1/** 对所有能访问本端口的人开放"
        )
    elif settings.agent_api_key:
        logger.info("Web 形态已启用 API Key 鉴权（AGENT_API_KEY）")

    # 3. 定时任务调度器（未获得租约时以 standby 运行）
    app.state.scheduler_service.start()

    if FRONTEND_DIST.exists():
        logger.info("检测到前端构建产物，托管于 / : %s", FRONTEND_DIST)
    yield
    app.state.scheduler_service.shutdown()
    app.state.research_manager.shutdown()
    # P3-15：等待在跑的**恢复任务**完成（优雅退出，不静默丢弃）
    try:
        app.state.run_executor.close(wait=True)
    except Exception as exc:  # noqa: BLE001 - 关闭失败不阻断退出
        logger.warning("恢复线程池关闭失败: %s", exc)
    # P2-01：回收常驻 MCP 会话（否则子进程残留 → 僵尸进程）
    try:
        app.state.mcp_manager.close_all_sessions()
    except Exception as exc:  # noqa: BLE001 - 回收失败不阻断关闭
        logger.warning("MCP 会话回收失败: %s", exc)
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


# ---------- Web 形态最小鉴权（P1-01） ----------
# 位置说明：本中间件**定义在 request_id 中间件之后** → 注册更晚 → 位于更内层，
# 因此它的 401 响应会经过 request_id 中间件，从而带上 ``X-Request-ID``。
@app.middleware("http")
async def api_key_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Web 形态下对 ``/api/v1/**`` 强制 API Key。

    - **仅在** ``AGENT_API_KEY`` 已配置、且**非桌面形态**时生效；
      桌面形态由会话守卫 + Host 白名单负责（``desktop_guard``），二者不冲突。
    - 未配置 Key 时**不启用**（单机自用是默认形态），启动日志会显式告警。
    - Key 可通过 ``X-API-Key`` 头、``Authorization: Bearer <key>`` 或
      ``?api_key=`` 查询参数携带（后者供 EventSource/SSE 使用——浏览器
      ``EventSource`` 无法自定义请求头）。
    - 比较用**常量时间**（``hmac.compare_digest``），避免时序侧信道。
    """
    if not settings.agent_api_key or settings.desktop_mode:
        return await call_next(request)
    if not request.url.path.startswith("/api/v1/"):
        return await call_next(request)

    provided = request.headers.get("X-API-Key") or request.query_params.get("api_key") or ""
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        provided = provided or auth_header[7:].strip()

    if not hmac.compare_digest(provided, settings.agent_api_key):
        logger.warning("API Key 校验失败: %s %s", request.method, request.url.path)
        # 中间件内直接返回响应（抛出的 HTTPException 不会经过异常处理器）
        return error_response(401, ErrorCode.AUTH, "缺少或无效的 API Key")
    return await call_next(request)


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


# ---------- 统一启动入口（P1-10） ----------
def run() -> None:
    """以**配置里的**绑定地址与端口启动服务。

    **P1-10 背景**：此前各文档与脚本用
    ``uvicorn app.main:app --host 0.0.0.0 --port 8000`` 启动，
    **绕过了配置中的 ``HOST``**（默认 ``127.0.0.1``）→ 实际默认绑定全网卡，
    「默认只监听回环」这条安全约束形同虚设。

    本入口让 ``HOST``/``PORT`` 成为**唯一真相**：

    - 默认 ``HOST=127.0.0.1`` → 只监听回环（单机自用，安全默认）；
    - 需要对外提供服务时**显式**设 ``HOST=0.0.0.0``
      （容器形态由 ``docker-compose.yml`` 显式覆盖——容器内绑全网卡是对的，
      对外入口由 Nginx 反代管控）。
    """
    import uvicorn

    loopback_only = settings.host in ("127.0.0.1", "localhost", "::1")
    logger.info(
        "启动服务 %s:%s（仅本机可达：%s）",
        settings.host, settings.port, "是" if loopback_only else "否 —— 对外暴露中",
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


# ---------- 桌面模式：会话守卫与引导端点 ----------
if settings.desktop_mode:
    from app.desktop.bootstrap import bootstrap_response, guard

    @app.middleware("http")
    async def desktop_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        """桌面模式下校验 Host 白名单与会话令牌。

        **W7-06 / AUD2-H15**：此前只覆盖 ``/api/v1/`` → SPA 回退路由、
        ``/__desktop/*``、``/docs``（Swagger 全量接口清单）、``/openapi.json``
        全部**绕过 Host 白名单** → DNS rebinding 下攻击者页面可直接读取
        API 文档；与 SPA 回退路径穿越（``AUD2-C01``）叠加后可**无凭据读取本地文件**。

        现在：Host 白名单覆盖**全路径**（静态资源除外，它们不泄露信息）。
        会话令牌仍然只对 ``/api/v1/`` 强制（引导端点必须免鉴权才能换到 Cookie）。
        """
        path = request.url.path
        # 静态资源不参与（图片/JS/CSS 无信息量，且量大）
        if path.startswith("/assets/") or path == "/favicon.ico":
            return await call_next(request)
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
        """SPA 路由回退：非 /api 路径一律返回 index.html；/api 未匹配路径保持 404。

        **W7-01 / AUD2-C01（路径穿越修复）**：此前 ``target = FRONTEND_DIST / full_path``
        后直接 ``target.is_file()`` 返回——``Path.is_file()`` 会跟随 ``..`` 解析，
        且 ``full_path`` 来自路径参数（``%2e%2e%2f`` 被 uvicorn 解码即成 ``../``），
        因此可读取 **dist 目录之外的任意本地文件**（如 ``~/.ssh/id_rsa``、``backend/.env``）。
        该路由**不匹配 ``/api/v1/`` 前缀**，因此**不经过桌面守卫的 Host 白名单与会话校验**。

        修复：``resolve()`` 后用 ``is_relative_to`` 确认仍落在 dist 根内，否则一律回退 index.html。
        """
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"API 路径不存在: /{full_path}")
        dist_root = FRONTEND_DIST.resolve()
        try:
            target = (dist_root / full_path).resolve()
        except (OSError, ValueError):  # pragma: no cover - 非法路径
            return FileResponse(dist_root / "index.html")
        # 必须落在 dist 根内，否则视为非法路径 → 回退到 SPA 首页
        if full_path and target.is_file() and target.is_relative_to(dist_root):
            return FileResponse(target)
        return FileResponse(dist_root / "index.html")
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


if __name__ == "__main__":
    run()

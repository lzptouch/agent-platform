/**
 * Fastify 应用（契约对齐：backend/app/main.py）。
 *
 * 关键点：
 * - `X-Request-ID` 全链路贯通；
 * - 统一错误体 `{code, message, detail, request_id}`；
 * - **桌面守卫**：Host 白名单 + 会话令牌（仅 `/api/v1/` 强制会话，静态资源豁免）；
 * - **SPA 回退** + 路径穿越防护；
 * - ⚠️ **不要启用 `@fastify/compress`**（会缓冲 SSE）。
 */
import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import multipart from "@fastify/multipart";
import { settings, type Settings } from "../shared/config.js";
import { getLogger } from "../shared/logger.js";
import {
  AppError,
  HttpError,
  REQUEST_ID_HEADER,
  errorBody,
  errorCodeFromStatus,
  getRequestId,
  sanitizeRequestId,
} from "../shared/errors.js";
import { runWithRequestId } from "../shared/errors.js";
import {
  COOKIE_NAME,
  HEADER_NAME,
  SESSION_TTL_SECONDS,
  hostAllowed,
  requestAuthorized,
} from "./bootstrap.js";
import { registerStatic } from "./static.js";
import { decorateServices, getServices } from "./context.js";
import { registerRoutes } from "./routes/index.js";

const logger = getLogger("http.app");

/** Fastify 请求类型增强（requestId）。 */
declare module "fastify" {
  interface FastifyRequest {
    requestId?: string;
  }
}

/** 构造应用实例。 */
export async function buildApp(s: Settings = settings): Promise<FastifyInstance> {
  const app = Fastify({
    logger: false,
    bodyLimit: s.upload_max_request_bytes as number,
  });

  // 上传解析（提供 req.parts()）
  await app.register(multipart, { limits: { fileSize: s.upload_max_file_bytes as number } });

  decorateServices(app);

  // ---------- 请求 ID ----------
  app.addHook("onRequest", async (req: FastifyRequest, reply: FastifyReply) => {
    const rid = sanitizeRequestId(req.headers[REQUEST_ID_HEADER.toLowerCase()] as string | undefined);
    // eslint-disable-next-line no-param-reassign
    (req as FastifyRequest & { requestId?: string }).requestId = rid;
    reply.header(REQUEST_ID_HEADER, rid);
  });

  // ---------- 桌面守卫（Host 白名单 + 会话） ----------
  app.addHook("onRequest", async (req, reply) => {
    if (!s.desktop_mode) return;
    const path = req.url.split("?")[0];
    // 静态资源不参与（无信息量，且量大）
    if (path.startsWith("/assets/") || path === "/favicon.ico") return;

    const host = req.headers.host;
    if (!hostAllowed(host, s)) {
      return reply.code(421).send(
        errorBody("E_AUTH", "非法 Host", "非法 Host", req.requestId),
      );
    }
    // 会话令牌只对 /api/v1/ 强制（引导端点必须免鉴权才能换到 Cookie）
    if (path.startsWith("/api/v1/")) {
      const headerValue = req.headers[HEADER_NAME.toLowerCase()] as string | undefined;
      const cookieValue = parseCookies(req.headers.cookie)[COOKIE_NAME];
      if (!requestAuthorized(headerValue, cookieValue, s)) {
        return reply.code(401).send(
          errorBody("E_AUTH", "桌面会话未建立，请重启应用", "桌面会话未建立，请重启应用", req.requestId),
        );
      }
    }
  });

  // ---------- 统一错误处理 ----------
  app.setErrorHandler((error, req, reply) => {
    const rid = req.requestId ?? getRequestId();
    if (error instanceof AppError) {
      return reply
        .code(error.statusCode)
        .header(REQUEST_ID_HEADER, rid)
        .send(errorBody(error.code, error.message, error.detail, rid));
    }
    if (error instanceof HttpError) {
      for (const [k, v] of Object.entries(error.headers)) reply.header(k, v);
      const message =
        typeof error.detail === "string" ? error.detail : "请求失败";
      return reply
        .code(error.statusCode)
        .header(REQUEST_ID_HEADER, rid)
        .send(errorBody(errorCodeFromStatus(error.statusCode), message, error.detail, rid));
    }
    // Fastify 校验错误（schema）
    const fastifyError = error as { statusCode?: number; message?: string; validation?: unknown };
    const status = fastifyError.statusCode ?? 500;
    if (status === 400 && fastifyError.validation !== undefined) {
      return reply
        .code(400)
        .header(REQUEST_ID_HEADER, rid)
        .send(
          errorBody(errorCodeFromStatus(400), "请求失败", fastifyError.message ?? null, rid),
        );
    }
    logger.error("未处理异常", { error: String(error), path: req.url });
    return reply
      .code(status >= 400 && status < 600 ? status : 500)
      .header(REQUEST_ID_HEADER, rid)
      .send(errorBody("E_INTERNAL", "服务内部错误", null, rid));
  });

  app.setNotFoundHandler(async (req, reply) => {
    const path = req.url.split("?")[0];
    if (path.startsWith("/api/")) {
      return reply
        .code(404)
        .send(errorBody("E_NOT_FOUND", "请求失败", `API 路径不存在: ${path}`, req.requestId));
    }
    // SPA 回退由 static 路由处理
    return reply.code(404).type("text/plain; charset=utf-8").send("Not Found");
  });

  // ---------- 业务路由 ----------
  await registerRoutes(app);

  // ---------- 桌面端点 ----------
  app.get("/__desktop/bootstrap", async (req, reply) => {
    const nonce = String((req.query as Record<string, string>)?.t ?? "");
    const { handleBootstrap } = await import("./bootstrap.js");
    const result = handleBootstrap(nonce, s);
    if (!result.ok) {
      return reply
        .code(result.statusCode)
        .send(errorBody(errorCodeFromStatus(result.statusCode), result.detail, result.detail, req.requestId));
    }
    return reply
      .code(302)
      .header("Location", "/")
      .header(
        "Set-Cookie",
        `${COOKIE_NAME}=${result.sessionId}; Path=/; Max-Age=${SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict`,
      )
      .send();
  });

  app.get("/__desktop/ping", async () => ({ ok: true }));

  app.get("/docs-info", async () => ({
    docs: "/docs",
    redoc: "/redoc",
    openapi: "/openapi.json",
    health: "/api/v1/health",
    ui: "/",
  }));

  // ---------- 静态资源（生产模式） ----------
  registerStatic(app, s.frontend_dist_dir);

  return app;
}

/** 解析 Cookie 头。 */
export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx <= 0) continue;
    const key = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (key) out[key] = decodeURIComponent(value);
  }
  return out;
}

/** 在指定 request id 上下文中执行（供 SSE 使用）。 */
export function withRequestId<T>(rid: string, fn: () => T): T {
  return runWithRequestId(rid, fn);
}

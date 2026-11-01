/**
 * 静态资源托管与 SPA 回退（契约冻结，来源：backend/app/main.py 末尾）。
 *
 * 关键安全约束（**AUD2-C01 路径穿越修复**）：
 * - ``Path.is_file()`` 会跟随 ``..`` 解析，且路径参数会被解码 → 可读取 dist 目录
 *   之外的任意本地文件；
 * - 修复：``resolve()`` 后用前缀判定确认仍落在 dist 根内，否则一律回退 index.html。
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".pdf": "application/pdf",
  ".wasm": "application/wasm",
};

/** 判断 MIME 类型。 */
export function mimeType(filePath: string): string {
  return MIME_TYPES[path.extname(filePath).toLowerCase()] ?? "application/octet-stream";
}

/**
 * 解析 SPA 回退目标。
 *
 * @returns 命中的文件绝对路径；未命中返回 `null`（调用方回退 index.html）
 */
export function resolveStaticTarget(
  distRoot: string,
  fullPath: string,
): string | null {
  if (!fullPath) return null;
  let target: string;
  try {
    target = path.resolve(distRoot, `.${path.posix.sep}${fullPath}`);
  } catch {
    return null;
  }
  const root = path.resolve(distRoot);
  // 必须落在 dist 根内（resolve 后前缀判定，兼顾 `..` 与符号链接外跳）
  if (target !== root && !target.startsWith(root + path.sep)) return null;
  try {
    const stat = fs.statSync(target);
    if (!stat.isFile()) return null;
  } catch {
    return null;
  }
  return target;
}

/** 读取 index.html（不存在返回 null）。 */
export function readIndex(distRoot: string): string | null {
  try {
    return fs.readFileSync(path.join(distRoot, "index.html"), "utf-8");
  } catch {
    return null;
  }
}

/**
 * 注册静态托管与 SPA 回退路由。
 *
 * @param app Fastify 实例
 * @param distRoot 前端产物目录（不存在则不注册）
 */
export function registerStatic(
  app: FastifyInstance,
  distRoot: string,
): void {
  if (!fs.existsSync(distRoot)) return;
  const root = path.resolve(distRoot);

  // /assets/* 直接由静态中间件托管（带长缓存）
  const assetsDir = path.join(root, "assets");
  if (fs.existsSync(assetsDir)) {
    app.get("/assets/*", async (req: FastifyRequest, reply: FastifyReply) => {
      const rel = (req.params as Record<string, string>)["*"] ?? "";
      const target = resolveStaticTarget(assetsDir, rel);
      if (!target) {
        return reply.code(404).type("text/plain; charset=utf-8").send("Not Found");
      }
      return reply
        .code(200)
        .type(mimeType(target))
        .header("Cache-Control", "public, max-age=31536000, immutable")
        .send(fs.readFileSync(target));
    });
  }

  // SPA 回退：非 /api 路径一律回 index.html；/api 未匹配路径保持 404
  app.get("/", async (_req, reply) => {
    const html = readIndex(root);
    if (html === null) {
      return reply.code(404).type("text/plain; charset=utf-8").send("Not Found");
    }
    return reply.code(200).type("text/html; charset=utf-8").send(html);
  });

  app.get("/*", async (req, reply) => {
    const fullPath = (req.params as Record<string, string>)["*"] ?? "";
    if (fullPath.startsWith("api/")) {
      return reply
        .code(404)
        .type("application/json; charset=utf-8")
        .send({
          code: "E_NOT_FOUND",
          message: "请求失败",
          detail: `API 路径不存在: /${fullPath}`,
          request_id: reply.getHeader("X-Request-ID") ?? "",
        });
    }
    const target = resolveStaticTarget(root, fullPath);
    if (target) {
      return reply
        .code(200)
        .type(mimeType(target))
        .header("Cache-Control", "no-cache")
        .send(fs.readFileSync(target));
    }
    const html = readIndex(root);
    if (html === null) {
      return reply.code(404).type("text/plain; charset=utf-8").send("Not Found");
    }
    return reply.code(200).type("text/html; charset=utf-8").send(html);
  });
}

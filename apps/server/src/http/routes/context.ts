/**
 * 上下文 / 记忆路由（契约对齐：app/api/v1/context.py）。
 *
 * 端点：`GET /memories` · `POST /memories` · `DELETE /memories` · `POST /memories/clear`
 *
 * 注：`/runs/{run_id}/cost` · `/cost/estimate` · `/sessions/{id}/context`
 * 三条路径已分别落在 `runs.ts` / `system.ts` / `sessions.ts`（路径唯一）。
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { getDb } from "../../db/client.js";
import { utcNow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";

/** 记忆目录（按作用域分文件）。 */
function memoryDir(scope: string): string {
  return path.join(settings.user_data_dir, "memory", scope);
}

export async function registerContextRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/memories", async (req) => {
    const q = req.query as Record<string, string>;
    const scope = q.scope ?? "user";
    const dir = memoryDir(scope);
    const items: Array<Record<string, unknown>> = [];
    if (fs.existsSync(dir)) {
      for (const file of fs.readdirSync(dir)) {
        if (!file.endsWith(".md")) continue;
        const full = path.join(dir, file);
        const stat = fs.statSync(full);
        items.push({
          path: full,
          scope,
          summary: firstLine(fs.readFileSync(full, "utf-8")),
          size: stat.size,
          updated_at: stat.mtime.toISOString(),
        });
      }
    }
    // 契约对齐（Python 侧）：`{items, enabled, max_injected, total, scope}`
    return {
      items,
      total: items.length,
      scope,
      enabled: settings.context_memory_enabled,
      max_injected: settings.context_memory_max,
    };
  });

  app.post("/api/v1/memories", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const scope = String(body.scope ?? "user");
    if (!["user", "workspace", "project"].includes(scope)) {
      throw new HttpError(422, "scope 必须是 user / workspace / project 之一");
    }
    const content = String(body.content ?? "");
    if (!content) throw new HttpError(422, "缺少 content");
    const name = String(body.name ?? `memory-${Date.now()}.md`);
    if (name.includes("/") || name.includes("..")) {
      throw new HttpError(422, "非法的记忆名称");
    }
    const dir = memoryDir(scope);
    fs.mkdirSync(dir, { recursive: true });
    const full = path.join(dir, name);
    fs.writeFileSync(full, content, "utf-8");
    // 同步索引
    const db = getDb();
    db.prepare(
      `INSERT INTO memory_index (path, scope, summary, tags, size, last_used_at, created_at, updated_at)
       VALUES (?, ?, ?, '[]', ?, NULL, ?, ?)`,
    ).run(full, scope, firstLine(content), Buffer.byteLength(content, "utf-8"), utcNow(), utcNow());
    return reply.code(201).send({ ok: true, path: full, scope, size: content.length });
  });

  app.delete("/api/v1/memories", async (req) => {
    const q = req.query as Record<string, string>;
    const target = String(q.path ?? "");
    if (!target) throw new HttpError(422, "缺少 path");
    const resolved = path.resolve(target);
    const allowedRoots = ["user", "workspace", "project"].map((s) => memoryDir(s));
    if (!allowedRoots.some((r) => resolved === r || resolved.startsWith(r + path.sep))) {
      throw new HttpError(403, "不允许删除该路径");
    }
    if (!fs.existsSync(resolved)) throw new HttpError(404, "记忆不存在");
    fs.rmSync(resolved, { force: true });
    getDb().prepare("DELETE FROM memory_index WHERE path = ?").run(resolved);
    return { ok: true, deleted: resolved };
  });

  app.post("/api/v1/memories/clear", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const scope = String(body.scope ?? "user");
    if (!["user", "workspace", "project"].includes(scope)) {
      throw new HttpError(422, "scope 必须是 user / workspace / project 之一");
    }
    const dir = memoryDir(scope);
    let removed = 0;
    if (fs.existsSync(dir)) {
      for (const file of fs.readdirSync(dir)) {
        if (!file.endsWith(".md")) continue;
        fs.rmSync(path.join(dir, file), { force: true });
        removed += 1;
      }
    }
    getDb().prepare("DELETE FROM memory_index WHERE scope = ?").run(scope);
    return { ok: true, scope, removed };
  });
}

/** 取首行作为摘要。 */
function firstLine(text: string): string {
  return (text.split("\n")[0] ?? "").slice(0, 200);
}

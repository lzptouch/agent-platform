/**
 * 会话路由（契约对齐：app/api/v1/sessions.py + context.py 的会话上下文端点）。
 *
 * 端点：`POST /` · `GET /` · `GET /{id}` · `PATCH /{id}` · `DELETE /{id}`
 *      · `DELETE /{id}/purge` · `GET /{id}/context`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { sessionService } from "../../domain/session/service.js";
import { getDb } from "../../db/client.js";
import { settings } from "../../shared/config.js";

export async function registerSessionRoutes(app: FastifyInstance): Promise<void> {
  app.post("/api/v1/sessions", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const mode = String(body.mode ?? "chat");
    const out = sessionService.create(
      mode,
      String(body.title ?? ""),
      Array.isArray(body.skills) ? (body.skills as string[]) : null,
      body.team_id ? String(body.team_id) : null,
      (body.config as Record<string, unknown>) ?? {},
    );
    return reply.code(201).send(out);
  });

  app.get("/api/v1/sessions", async (req) => {
    const q = req.query as Record<string, string>;
    const page = Number(q.page ?? 1);
    const pageSize = Number(q.page_size ?? 20);
    if (!Number.isFinite(page) || page < 1) throw new HttpError(422, "page 必须 ≥ 1");
    if (!Number.isFinite(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new HttpError(422, "page_size 必须在 1~100 之间");
    }
    const mode = q.mode ?? null;
    if (mode && !["chat", "plan", "work"].includes(mode)) {
      throw new HttpError(422, "mode 必须是 chat / plan / work 之一");
    }
    const { items, total } = sessionService.list(
      mode,
      page,
      pageSize,
      q.include_archived === "true",
      q.only_trashed === "true",
    );
    return { items, total, page, page_size: pageSize };
  });

  app.get("/api/v1/sessions/:session_id", async (req) => {
    const sessionId = String((req.params as Record<string, string>).session_id);
    const q = req.query as Record<string, string>;
    const limit = Number(q.message_limit ?? 100);
    const beforeSeq = q.before_seq ? Number(q.before_seq) : null;
    const detail = sessionService.get(sessionId, limit, beforeSeq);
    if (!detail) throw new HttpError(404, "会话不存在");
    return detail;
  });

  app.patch("/api/v1/sessions/:session_id", async (req) => {
    const sessionId = String((req.params as Record<string, string>).session_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    if (body.title !== undefined && body.title !== null) {
      const title = String(body.title);
      if (title.length > 200) throw new HttpError(422, "title 长度不能超过 200");
    }
    const out = sessionService.update(sessionId, {
      title: body.title !== undefined ? (body.title as string | null) : undefined,
      archived: body.archived !== undefined ? (body.archived as boolean | null) : undefined,
      skills: body.skills !== undefined ? (body.skills as string[] | null) : undefined,
      teamId: body.team_id !== undefined ? (body.team_id as string | null) : undefined,
      config: body.config !== undefined ? (body.config as Record<string, unknown> | null) : undefined,
    });
    if (!out) throw new HttpError(404, "会话不存在");
    return out;
  });

  app.delete("/api/v1/sessions/:session_id", async (req, reply) => {
    const sessionId = String((req.params as Record<string, string>).session_id);
    if (!sessionService.delete(sessionId)) throw new HttpError(404, "会话不存在");
    return reply.code(204).send();
  });

  app.delete("/api/v1/sessions/:session_id/purge", async (req) => {
    const sessionId = String((req.params as Record<string, string>).session_id);
    if (!sessionService.purge(sessionId)) throw new HttpError(404, "会话不存在");
    return { ok: true, purged: sessionId };
  });

  app.get("/api/v1/sessions/:session_id/context", async (req) => {
    const sessionId = String((req.params as Record<string, string>).session_id);
    const session = sessionService.get(sessionId, 1);
    if (!session) throw new HttpError(404, "会话不存在");
    const db = getDb();
    const history = sessionService.buildHistory(
      sessionId,
      settings.session_history_limit,
      settings.session_history_max_chars,
    );
    const runs = db
      .prepare(
        "SELECT COUNT(*) AS c FROM runs WHERE session_id = ?",
      )
      .get(sessionId) as { c: number };
    return {
      session_id: sessionId,
      mode: session.mode,
      history_limit: settings.session_history_limit,
      history_max_chars: settings.session_history_max_chars,
      message_count: session.message_count,
      run_count: runs?.c ?? 0,
      history,
      estimated_tokens: history.reduce(
        (sum, h) => sum + Math.ceil(h.content.length / 4),
        0,
      ),
      budget_ratio: settings.context_budget_ratio,
    };
  });
}

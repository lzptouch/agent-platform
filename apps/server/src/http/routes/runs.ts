/**
 * 运行账本路由（契约对齐：app/api/v1/runs.py）。
 *
 * 端点：`GET /` · `GET /{id}` · `GET /{id}/events` · `GET /{id}/stream`（SSE）
 *      · `POST /{id}/cancel` · `POST /{id}/steer` · `GET /{id}/cost`
 *      · `GET /{id}/changes` · `GET /{id}/artifacts`
 *      · `GET /{id}/artifacts/{aid}/download` · `POST /{id}/artifacts/{aid}/save-as`
 */
import fs from "node:fs";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { sse } from "../sse.js";
import { runService } from "../../domain/run/service.js";
import { runExecutor } from "../../domain/run/executor.js";
import { getDb } from "../../db/client.js";
import { aggregateRun } from "../../domain/exec/accounting.js";
import { priceTable } from "../../domain/accounting/pricing.js";
import { settings } from "../../shared/config.js";

const STREAM_POLL_MS = 300;
const STREAM_MAX_SECONDS = 3600;

export async function registerRunRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/runs", async (req) => {
    const q = req.query as Record<string, string>;
    const page = Number(q.page ?? 1);
    const pageSize = Number(q.page_size ?? 20);
    const { items, total } = runService.listRuns(
      q.task_id ?? null,
      q.status ?? null,
      page,
      pageSize,
    );
    return { items, total, page, page_size: pageSize };
  });

  app.get("/api/v1/runs/:run_id", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const run = runService.getRun(runId);
    if (!run) throw new HttpError(404, "运行不存在");
    return run;
  });

  app.get("/api/v1/runs/:run_id/events", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const q = req.query as Record<string, string>;
    const afterSeq = Number(q.after_seq ?? 0);
    const limit = Math.min(Number(q.limit ?? 500), 1000);
    const { items, lastSeq, status, hasMore } = runService.listEvents(runId, afterSeq, limit);
    return {
      items,
      last_seq: lastSeq,
      status,
      has_more: hasMore,
    };
  });

  // SSE：DB tail，支持 `Last-Event-ID` 断线续传
  app.get("/api/v1/runs/:run_id/stream", async (req, reply) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const q = req.query as Record<string, string>;
    const lastEventId = req.headers["last-event-id"];
    let cursor = Number(q.after_seq ?? (lastEventId ? Number(lastEventId) : 0)) || 0;
    const maxEvents = q.max_events ? Number(q.max_events) : null;
    const channel = sse(reply);
    const deadline = Date.now() + STREAM_MAX_SECONDS * 1000;
    let sent = 0;

    try {
      while (Date.now() < deadline) {
        const { items, lastSeq, status } = runService.listEvents(runId, cursor, 200);
        for (const item of items) {
          if (channel.closed) return reply;
          channel.send(item.type, item.payload, item.seq);
          cursor = lastSeq;
          sent += 1;
          if (maxEvents !== null && sent >= maxEvents) {
            channel.end();
            return reply;
          }
        }
        if (["success", "failed", "skipped", "interrupted", "rejected"].includes(status)) {
          channel.send("done", { status });
          break;
        }
        channel.ping();
        await new Promise((r) => setTimeout(r, STREAM_POLL_MS));
      }
    } finally {
      channel.end();
    }
    return reply;
  });

  app.post("/api/v1/runs/:run_id/cancel", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const run = runService.getRun(runId);
    if (!run) throw new HttpError(404, "运行不存在");
    runExecutor.cancel(runId);
    return { ok: true, run_id: runId, status: runService.getRun(runId)?.status ?? "interrupted" };
  });

  app.post("/api/v1/runs/:run_id/steer", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const run = runService.getRun(runId);
    if (!run) throw new HttpError(404, "运行不存在");
    const instructions = Array.isArray(body.instructions)
      ? (body.instructions as string[]).map((s) => String(s)).filter(Boolean)
      : [];
    if (!instructions.length) throw new HttpError(422, "缺少 instructions");
    const modes = Array.isArray(body.modes) ? (body.modes as string[]) : [];
    runExecutor.steer(runId, instructions);
    return { ok: true, run_id: runId, injected: instructions.length, modes };
  });

  app.get("/api/v1/runs/:run_id/cost", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const run = runService.getRun(runId);
    if (!run) throw new HttpError(404, "运行不存在");
    const agg = aggregateRun(runId);
    return {
      run_id: runId,
      prompt_tokens: agg.prompt_tokens,
      completion_tokens: agg.completion_tokens,
      llm_calls: agg.llm_calls,
      estimated_cost: agg.estimated_cost,
      price_table: priceTable(),
    };
  });

  app.get("/api/v1/runs/:run_id/changes", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM changes WHERE run_id = ? ORDER BY id")
      .all(runId) as Array<Record<string, unknown>>;
    return { items: rows, total: rows.length };
  });

  app.get("/api/v1/runs/:run_id/artifacts", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM artifacts WHERE run_id = ? ORDER BY id")
      .all(runId) as Array<Record<string, unknown>>;
    return { items: rows, total: rows.length };
  });

  app.get("/api/v1/runs/:run_id/artifacts/:artifact_id/download", async (req, reply) => {
    const params = req.params as Record<string, string>;
    const db = getDb();
    const row = db
      .prepare("SELECT * FROM artifacts WHERE id = ? AND run_id = ?")
      .get(Number(params.artifact_id), params.run_id) as
      | { path: string; title: string | null; mime: string | null }
      | undefined;
    if (!row) throw new HttpError(404, "产物不存在");
    if (!fs.existsSync(row.path)) throw new HttpError(404, "产物文件不存在");
    const filename = row.title ?? path.basename(row.path);
    return reply
      .code(200)
      .type(row.mime ?? "application/octet-stream")
      .header("Content-Disposition", `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`)
      .send(fs.readFileSync(row.path));
  });

  app.post("/api/v1/runs/:run_id/artifacts/:artifact_id/save-as", async (req) => {
    const params = req.params as Record<string, string>;
    const body = (req.body ?? {}) as Record<string, unknown>;
    const db = getDb();
    const row = db
      .prepare("SELECT * FROM artifacts WHERE id = ? AND run_id = ?")
      .get(Number(params.artifact_id), params.run_id) as
      | { id: number; path: string; title: string | null }
      | undefined;
    if (!row) throw new HttpError(404, "产物不存在");
    const target = String(body.path ?? body.target ?? "").trim();
    if (!target) throw new HttpError(422, "缺少 path");
    const destDir = path.isAbsolute(target) ? path.dirname(target) : settings.output_dir;
    fs.mkdirSync(destDir, { recursive: true });
    const dest = path.isAbsolute(target)
      ? target
      : path.join(settings.output_dir, target);
    fs.copyFileSync(row.path, dest);
    return { ok: true, saved_to: dest, artifact_id: row.id };
  });
}

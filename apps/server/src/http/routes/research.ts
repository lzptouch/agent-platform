/**
 * 深度研究路由（契约对齐：app/api/v1/research.py）。
 *
 * 端点：`GET /health` · `POST /` · `GET /` · `GET /{id}` · `GET /{id}/result`
 *      · `GET /{id}/stream`（SSE）· `DELETE /{id}`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { settings } from "../../shared/config.js";
import { sse } from "../sse.js";
import { researchManager } from "../../domain/research/manager.js";

export async function registerResearchRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/research/health", async () => {
    const provider = settings.bocha_configured
      ? "bocha"
      : settings.web_search_available
        ? "serper"
        : "none";
    const health = researchManager.health();
    return {
      enabled: true,
      search_provider: provider,
      search_configured: provider !== "none",
      llm_configured: settings.has_api_key,
      default_model: settings.default_model,
      max_concurrent_tasks: settings.research_max_concurrent,
      output_dir: settings.research_output_abs,
      total_tasks: Number(health.tasks ?? 0),
      running_tasks: 0,
    };
  });

  app.post("/api/v1/research", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const query = String(body.query ?? body.task ?? "");
    if (!query) throw new HttpError(422, "缺少 query");
    const task = researchManager.create(query);
    // 后台推进（不阻塞响应）
    void researchManager.run(task.id).catch(() => {
      /* 错误已记录在任务内 */
    });
    const failed = !settings.research_configured;
    return reply.code(200).send({
      task_id: task.id,
      status: failed ? "failed" : "pending",
      message: failed
        ? "未配置 BOCHA_API_KEY / SERPER_API_KEY —— 检索能力不可用，任务将失败"
        : "研究任务已提交",
      created_at: task.created_at,
    });
  });

  app.get("/api/v1/research", async () => {
    const items = researchManager.list();
    return {
      total: items.length,
      tasks: items.map((t) => ({
        task_id: t.id,
        original_task: t.query,
        status: t.status,
        created_at: t.created_at,
        quality_score: t.quality_score,
      })),
    };
  });

  app.get("/api/v1/research/:task_id", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const task = researchManager.get(taskId);
    if (!task) throw new HttpError(404, "研究任务不存在");
    return {
      task_id: task.id,
      status: task.status,
      progress: task.stages,
      progress_summary: { stages: task.stages.length },
      original_task: task.query,
      created_at: task.created_at,
      started_at: task.stages[0]?.at ?? null,
      completed_at: task.updated_at,
      quality_score: task.quality_score,
      iteration_count: task.iterations,
      error_message: task.error,
    };
  });

  app.get("/api/v1/research/:task_id/result", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const task = researchManager.get(taskId);
    if (!task) throw new HttpError(404, "研究任务不存在");
    return {
      task_id: task.id,
      status: task.status,
      report: task.report,
      quality_score: task.quality_score,
      iteration_count: task.iterations,
      duration: null,
      metadata: { sources: task.sources },
    };
  });

  app.get("/api/v1/research/:task_id/stream", async (req, reply) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    if (!researchManager.get(taskId)) throw new HttpError(404, "研究任务不存在");
    const channel = sse(reply);
    const unsubscribe = researchManager.subscribe(taskId, (event) => {
      if (channel.closed) return;
      channel.send(event.type, event);
    });
    const deadline = Date.now() + 3600_000;
    try {
      while (Date.now() < deadline) {
        const task = researchManager.get(taskId);
        if (!task) break;
        if (["done", "failed", "cancelled"].includes(task.status)) {
          channel.send("done", { status: task.status, task_id: taskId });
          break;
        }
        channel.ping();
        await new Promise((r) => setTimeout(r, 500));
      }
    } finally {
      unsubscribe();
      channel.end();
    }
    return reply;
  });

  app.delete("/api/v1/research/:task_id", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    if (!researchManager.delete(taskId)) throw new HttpError(404, "研究任务不存在");
    return { ok: true, deleted: taskId };
  });
}

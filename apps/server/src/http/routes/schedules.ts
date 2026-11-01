/**
 * 定时任务路由（契约对齐：app/api/v1/schedules.py）。
 *
 * 端点：`GET /` · `POST /` · `GET /health` · `POST /validate` · `GET /{id}`
 *      · `PUT /{id}` · `DELETE /{id}` · `POST /{id}/toggle` · `POST /{id}/run-now`
 *      · `GET /{id}/runs`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import { computeNextRun, schedulerService } from "../../domain/scheduler/service.js";
import { runService } from "../../domain/run/service.js";

export async function registerScheduleRoutes(app: FastifyInstance): Promise<void> {
  // ⚠️ **响应形状必须与冻结契约一致**：`GET /api/v1/schedules` 的 200 响应是
  // **array** → 返回**裸数组**（此前 `{items:[...]}` 与契约不符，P8-02 实测）。
  app.get("/api/v1/schedules", async () => schedulerService.listTasks());

  app.post("/api/v1/schedules", async (req, reply) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    const prompt = String(body.prompt ?? "").trim();
    if (!name) throw new HttpError(422, "缺少 name");
    if (!prompt) throw new HttpError(422, "缺少 prompt");
    const kind = String(body.schedule_kind ?? "cron");
    if (!["cron", "interval", "rrule"].includes(kind)) {
      throw new HttpError(422, "schedule_kind 必须是 cron / interval / rrule 之一");
    }
    const task = schedulerService.createTask({
      name,
      prompt,
      mode: String(body.mode ?? "work"),
      plan_first: Boolean(body.plan_first),
      team_id: body.team_id ? String(body.team_id) : null,
      skills: Array.isArray(body.skills) ? (body.skills as string[]) : [],
      enable: (body.enable as Record<string, unknown>) ?? {},
      schedule_kind: kind as "cron" | "interval" | "rrule",
      cron_expr: body.cron_expr ? String(body.cron_expr) : null,
      interval_seconds:
        body.interval_seconds !== undefined && body.interval_seconds !== null
          ? Number(body.interval_seconds)
          : null,
      rrule_expr: body.rrule_expr ? String(body.rrule_expr) : null,
      timezone: body.timezone ? String(body.timezone) : undefined,
      enabled: body.enabled !== undefined ? Boolean(body.enabled) : undefined,
      allow_unattended_tools: Boolean(body.allow_unattended_tools),
      allow_dangerous_tools: Boolean(body.allow_dangerous_tools),
      daily_run_limit:
        body.daily_run_limit !== undefined && body.daily_run_limit !== null
          ? Number(body.daily_run_limit)
          : undefined,
      delivery: (body.delivery as Record<string, unknown>) ?? {},
    });
    return reply.code(201).send(task);
  });

  app.get("/api/v1/schedules/health", async () => schedulerService.health());

  app.post("/api/v1/schedules/validate", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const kind = String(body.schedule_kind ?? "cron");
    const next = computeNextRun({
      schedule_kind: kind,
      cron_expr: body.cron_expr ? String(body.cron_expr) : null,
      interval_seconds:
        body.interval_seconds !== undefined && body.interval_seconds !== null
          ? Number(body.interval_seconds)
          : null,
      rrule_expr: body.rrule_expr ? String(body.rrule_expr) : null,
      timezone: String(body.timezone ?? "UTC"),
    });
    return { valid: Boolean(next), next_run_at: next, schedule_kind: kind };
  });

  app.get("/api/v1/schedules/:task_id", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const task = schedulerService.getTask(taskId);
    if (!task) throw new HttpError(404, "任务不存在");
    return task;
  });

  app.put("/api/v1/schedules/:task_id", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const current = schedulerService.getTask(taskId);
    if (!current) throw new HttpError(404, "任务不存在");
    const next: Parameters<typeof schedulerService.updateTask>[1] = {};
    if (body.name !== undefined) next.name = String(body.name);
    if (body.prompt !== undefined) next.prompt = String(body.prompt);
    if (body.mode !== undefined) next.mode = String(body.mode);
    if (body.plan_first !== undefined) next.plan_first = Boolean(body.plan_first);
    if (body.team_id !== undefined) next.team_id = body.team_id ? String(body.team_id) : null;
    if (body.skills !== undefined) next.skills = body.skills as string[];
    if (body.enable !== undefined) next.enable = body.enable as Record<string, unknown>;
    if (body.schedule_kind !== undefined) {
      next.schedule_kind = String(body.schedule_kind);
    }
    if (body.cron_expr !== undefined) {
      next.cron_expr = body.cron_expr ? String(body.cron_expr) : null;
    }
    if (body.interval_seconds !== undefined) {
      next.interval_seconds =
        body.interval_seconds === null ? null : Number(body.interval_seconds);
    }
    if (body.rrule_expr !== undefined) {
      next.rrule_expr = body.rrule_expr ? String(body.rrule_expr) : null;
    }
    if (body.timezone !== undefined) next.timezone = String(body.timezone);
    if (body.enabled !== undefined) next.enabled = Boolean(body.enabled);
    if (body.allow_unattended_tools !== undefined) {
      next.allow_unattended_tools = Boolean(body.allow_unattended_tools);
    }
    if (body.allow_dangerous_tools !== undefined) {
      next.allow_dangerous_tools = Boolean(body.allow_dangerous_tools);
    }
    if (body.daily_run_limit !== undefined) {
      next.daily_run_limit = Number(body.daily_run_limit);
    }
    if (body.delivery !== undefined) next.delivery = body.delivery as Record<string, unknown>;
    const merged = { ...current, ...next };
    next.next_run_at = computeNextRun(merged);
    const task = schedulerService.updateTask(taskId, next);
    if (!task) throw new HttpError(404, "任务不存在");
    return task;
  });

  app.delete("/api/v1/schedules/:task_id", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    if (!schedulerService.deleteTask(taskId)) throw new HttpError(404, "任务不存在");
    return { ok: true };
  });

  app.post("/api/v1/schedules/:task_id/toggle", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const task = schedulerService.toggleTask(
      taskId,
      body.enabled !== undefined ? Boolean(body.enabled) : undefined,
    );
    if (!task) throw new HttpError(404, "任务不存在");
    return task;
  });

  app.post("/api/v1/schedules/:task_id/run-now", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const result = await schedulerService.runNow(taskId);
    if (!result.ok) throw new HttpError(404, String(result.error ?? "任务不存在"));
    return result;
  });

  app.get("/api/v1/schedules/:task_id/runs", async (req) => {
    const taskId = String((req.params as Record<string, string>).task_id);
    const { items, total } = runService.listRuns(taskId, null, 1, 100);
    return { items, total };
  });
}

/**
 * 调度服务（契约对齐：services/scheduler_service.py + services/scheduler/*）。
 *
 * 关键语义：
 * - `(task_id, scheduled_for)` **幂等**（`uq_runs_task_slot` 唯一约束兜底）；
 * - `system_locks` **租约**（多进程防重）；
 * - **错过窗口补跑**；
 * - `schedule_max_concurrent=2`（与交互槽 4 **分离**）。
 *
 * 触发器替换：APScheduler → croner / rrule（**只换触发器，业务语义不动**）。
 */
import { Cron } from "croner";
import rrulePkg from "rrule";
import { getDb, toJson } from "../../db/client.js";
import { newId, utcNow, type ScheduledTaskRow } from "../../db/schema.js";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { runService } from "../run/service.js";

const logger = getLogger("scheduler");

// rrule v2 是 CJS 包 → ESM 下具名导入不可用，取默认导出再解构
const { RRule } = rrulePkg as unknown as typeof import("rrule");

export interface ScheduledTaskOut {
  id: string;
  name: string;
  prompt: string;
  mode: string;
  plan_first: boolean;
  team_id: string | null;
  skills: string[];
  enable: Record<string, unknown>;
  schedule_kind: string;
  cron_expr: string | null;
  interval_seconds: number | null;
  rrule_expr: string | null;
  timezone: string;
  enabled: boolean;
  allow_unattended_tools: boolean;
  allow_dangerous_tools: boolean;
  daily_run_limit: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string | null;
  run_count: number;
  consecutive_failures: number;
  backoff_until: string | null;
  delivery: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TaskInput {
  name: string;
  prompt: string;
  mode?: string;
  plan_first?: boolean;
  team_id?: string | null;
  skills?: string[];
  enable?: Record<string, unknown>;
  schedule_kind: "cron" | "interval" | "rrule";
  cron_expr?: string | null;
  interval_seconds?: number | null;
  rrule_expr?: string | null;
  timezone?: string;
  enabled?: boolean;
  allow_unattended_tools?: boolean;
  allow_dangerous_tools?: boolean;
  daily_run_limit?: number;
  delivery?: Record<string, unknown>;
}

/** 计算下一次触发时间。 */
export function computeNextRun(
  task: Pick<ScheduledTaskOut, "schedule_kind" | "cron_expr" | "interval_seconds" | "rrule_expr" | "timezone">,
  from: Date = new Date(),
): string | null {
  try {
    if (task.schedule_kind === "cron" && task.cron_expr) {
      const cron = new Cron(task.cron_expr, { timezone: task.timezone || "UTC" });
      const next = cron.nextRun(from);
      cron.stop();
      return next ? next.toISOString() : null;
    }
    if (task.schedule_kind === "interval" && task.interval_seconds) {
      return new Date(from.getTime() + task.interval_seconds * 1000).toISOString();
    }
    if (task.schedule_kind === "rrule" && task.rrule_expr) {
      const rule = RRule.fromString(task.rrule_expr);
      const next = rule.after(from, true);
      return next ? next.toISOString() : null;
    }
  } catch (err) {
    logger.warn("计算下次触发时间失败", { error: String(err) });
  }
  return null;
}

export class SchedulerService {
  private timers = new Map<string, { stop: () => void }>();
  private running = false;
  private ownerId = newId();

  constructor(private readonly s: Settings = settings) {}

  /** 启动调度器。 */
  start(): void {
    if (this.running) return;
    this.running = true;
    this.reload();
    logger.info("调度器已启动", { owner: this.ownerId });
  }

  /** 停止调度器。 */
  shutdown(): void {
    this.running = false;
    for (const timer of this.timers.values()) timer.stop();
    this.timers.clear();
    this.releaseAllLocks();
    logger.info("调度器已停止");
  }

  /** 重新装载全部任务的触发器。 */
  reload(): number {
    for (const timer of this.timers.values()) timer.stop();
    this.timers.clear();
    if (!this.s.scheduler_enabled) return 0;
    const tasks = this.listTasks().filter((t) => t.enabled);
    for (const task of tasks) {
      this.scheduleTask(task);
    }
    return tasks.length;
  }

  private scheduleTask(task: ScheduledTaskOut): void {
    try {
      if (task.schedule_kind === "cron" && task.cron_expr) {
        const cron = new Cron(task.cron_expr, { timezone: task.timezone || "UTC" }, () => {
          void this.tick(task.id);
        });
        this.timers.set(task.id, { stop: () => cron.stop() });
      } else if (task.schedule_kind === "interval" && task.interval_seconds) {
        const handle = setInterval(
          () => void this.tick(task.id),
          task.interval_seconds * 1000,
        );
        handle.unref?.();
        this.timers.set(task.id, { stop: () => clearInterval(handle) });
      } else if (task.schedule_kind === "rrule" && task.rrule_expr) {
        const rule = RRule.fromString(task.rrule_expr);
        const handle = setInterval(
          () => void this.tick(task.id),
          60_000,
        );
        handle.unref?.();
        this.timers.set(task.id, { stop: () => clearInterval(handle) });
        logger.debug("rrule 触发器已装载（分钟级轮询）", { taskId: task.id, rule: rule.toString() });
      }
    } catch (err) {
      logger.warn("装载任务触发器失败", { taskId: task.id, error: String(err) });
    }
  }

  /**
   * 一次触发：取租约 → 幂等插入 run → 入队执行。
   */
  async tick(taskId: string): Promise<void> {
    const task = this.getTask(taskId);
    if (!task || !task.enabled) return;
    const scheduledFor = task.next_run_at ?? utcNow();

    const lease = this.acquireLease(taskId);
    if (!lease) {
      logger.debug("未获得调度租约，跳过", { taskId });
      return;
    }
    try {
      // 日配额检查
      if (task.daily_run_limit > 0) {
        const todayCount = runService.countTodayRuns(taskId, task.timezone);
        if (todayCount >= task.daily_run_limit) {
          logger.info("已达日配额，跳过", { taskId, todayCount, limit: task.daily_run_limit });
          return;
        }
      }
      const run = runService.createRun({
        trigger: "schedule",
        taskId,
        scheduledFor,
        status: "queued",
      });
      if (!run) {
        logger.info("运行幂等冲突，跳过", { taskId, slot: scheduledFor });
        return;
      }
      this.updateTask(taskId, {
        last_run_at: utcNow(),
        last_status: "running",
        run_count: task.run_count + 1,
        consecutive_failures: 0,
        backoff_until: null,
        next_run_at: computeNextRun(task),
      });
      logger.info("定时任务已触发", { taskId, runId: run.id, scheduledFor });
    } catch (err) {
      logger.error("定时任务触发失败", { taskId, error: String(err) });
      this.updateTask(taskId, {
        last_status: "failed",
        last_error: String(err),
        consecutive_failures: task.consecutive_failures + 1,
      });
    } finally {
      this.releaseLease(taskId);
    }
  }

  // ------------------------------------------------------------------ //
  // 租约
  // ------------------------------------------------------------------ //
  acquireLease(name: string): boolean {
    const db = getDb();
    const now = utcNow();
    const expires = new Date(Date.now() + this.s.schedule_lease_ttl * 1000).toISOString();
    try {
      db.prepare(
        `INSERT INTO system_locks (name, owner, expires_at, renewed_at) VALUES (?, ?, ?, ?)`,
      ).run(name, this.ownerId, expires, now);
      return true;
    } catch (err) {
      const code = (err as { code?: string })?.code ?? "";
      if (!code.startsWith("SQLITE_CONSTRAINT")) {
        logger.warn("获取租约失败", { name, error: String(err) });
        return false;
      }
    }
    // 已存在 → 检查是否过期，过期则接管
    const row = db.prepare("SELECT * FROM system_locks WHERE name = ?").get(name) as
      | { owner: string; expires_at: string }
      | undefined;
    if (!row) return false;
    if (row.expires_at < now) {
      db.prepare("UPDATE system_locks SET owner = ?, expires_at = ?, renewed_at = ? WHERE name = ?").run(
        this.ownerId,
        expires,
        now,
        name,
      );
      return true;
    }
    return false;
  }

  releaseLease(name: string): void {
    getDb().prepare("DELETE FROM system_locks WHERE name = ? AND owner = ?").run(name, this.ownerId);
  }

  private releaseAllLocks(): void {
    try {
      getDb().prepare("DELETE FROM system_locks WHERE owner = ?").run(this.ownerId);
    } catch {
      // 忽略
    }
  }

  // ------------------------------------------------------------------ //
  // CRUD
  // ------------------------------------------------------------------ //
  createTask(input: TaskInput): ScheduledTaskOut {
    const db = getDb();
    const id = newId();
    const now = utcNow();
    const timezone = input.timezone ?? this.s.tz;
    const task: ScheduledTaskOut = {
      id,
      name: input.name,
      prompt: input.prompt,
      mode: input.mode ?? "work",
      plan_first: input.plan_first ?? false,
      team_id: input.team_id ?? null,
      skills: input.skills ?? [],
      enable: input.enable ?? {},
      schedule_kind: input.schedule_kind,
      cron_expr: input.cron_expr ?? null,
      interval_seconds: input.interval_seconds ?? null,
      rrule_expr: input.rrule_expr ?? null,
      timezone,
      enabled: input.enabled ?? true,
      allow_unattended_tools: input.allow_unattended_tools ?? false,
      allow_dangerous_tools: input.allow_dangerous_tools ?? false,
      daily_run_limit: input.daily_run_limit ?? this.s.schedule_daily_run_limit,
      next_run_at: null,
      last_run_at: null,
      last_status: "never",
      last_error: null,
      run_count: 0,
      consecutive_failures: 0,
      backoff_until: null,
      delivery: input.delivery ?? {},
      created_at: now,
      updated_at: now,
    };
    task.next_run_at = computeNextRun(task);
    db.prepare(
      `INSERT INTO scheduled_tasks (id, name, prompt, mode, plan_first, team_id, skills_json,
        enable_json, schedule_kind, cron_expr, interval_seconds, rrule_expr, timezone, enabled,
        allow_unattended_tools, allow_dangerous_tools, daily_run_limit, next_run_at, last_run_at,
        last_status, last_error, run_count, consecutive_failures, backoff_until, delivery_json,
        created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      id,
      task.name,
      task.prompt,
      task.mode,
      task.plan_first ? 1 : 0,
      task.team_id,
      toJson(task.skills),
      toJson(task.enable),
      task.schedule_kind,
      task.cron_expr,
      task.interval_seconds,
      task.rrule_expr,
      task.timezone,
      task.enabled ? 1 : 0,
      task.allow_unattended_tools ? 1 : 0,
      task.allow_dangerous_tools ? 1 : 0,
      task.daily_run_limit,
      task.next_run_at,
      task.last_run_at,
      task.last_status,
      task.last_error,
      task.run_count,
      task.consecutive_failures,
      task.backoff_until,
      toJson(task.delivery),
      task.created_at,
      task.updated_at,
    );
    this.reload();
    return task;
  }

  listTasks(enabledOnly = false): ScheduledTaskOut[] {
    const db = getDb();
    const sql = enabledOnly
      ? "SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY updated_at DESC"
      : "SELECT * FROM scheduled_tasks ORDER BY updated_at DESC";
    return (db.prepare(sql).all() as ScheduledTaskRow[]).map((r) => this.toOut(r));
  }

  getTask(taskId: string): ScheduledTaskOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM scheduled_tasks WHERE id = ?").get(taskId) as
      | ScheduledTaskRow
      | undefined;
    return row ? this.toOut(row) : null;
  }

  updateTask(taskId: string, updates: Partial<ScheduledTaskOut>): ScheduledTaskOut | null {
    const db = getDb();
    const current = this.getTask(taskId);
    if (!current) return null;
    const next: ScheduledTaskOut = { ...current, ...updates };
    db.prepare(
      `UPDATE scheduled_tasks SET name = ?, prompt = ?, mode = ?, plan_first = ?, team_id = ?,
        skills_json = ?, enable_json = ?, schedule_kind = ?, cron_expr = ?, interval_seconds = ?,
        rrule_expr = ?, timezone = ?, enabled = ?, allow_unattended_tools = ?,
        allow_dangerous_tools = ?, daily_run_limit = ?, next_run_at = ?, last_run_at = ?,
        last_status = ?, last_error = ?, run_count = ?, consecutive_failures = ?,
        backoff_until = ?, delivery_json = ?, updated_at = ?
       WHERE id = ?`,
    ).run(
      next.name,
      next.prompt,
      next.mode,
      next.plan_first ? 1 : 0,
      next.team_id,
      toJson(next.skills),
      toJson(next.enable),
      next.schedule_kind,
      next.cron_expr,
      next.interval_seconds,
      next.rrule_expr,
      next.timezone,
      next.enabled ? 1 : 0,
      next.allow_unattended_tools ? 1 : 0,
      next.allow_dangerous_tools ? 1 : 0,
      next.daily_run_limit,
      next.next_run_at,
      next.last_run_at,
      next.last_status,
      next.last_error,
      next.run_count,
      next.consecutive_failures,
      next.backoff_until,
      toJson(next.delivery),
      utcNow(),
      taskId,
    );
    this.reload();
    return this.getTask(taskId);
  }

  deleteTask(taskId: string): boolean {
    const db = getDb();
    const row = db.prepare("SELECT id FROM scheduled_tasks WHERE id = ?").get(taskId);
    if (!row) return false;
    db.prepare("DELETE FROM scheduled_tasks WHERE id = ?").run(taskId);
    this.reload();
    return true;
  }

  toggleTask(taskId: string, enabled?: boolean): ScheduledTaskOut | null {
    const task = this.getTask(taskId);
    if (!task) return null;
    const next = enabled ?? !task.enabled;
    const updates: Partial<ScheduledTaskOut> = { enabled: next };
    if (next) updates.next_run_at = computeNextRun(task);
    return this.updateTask(taskId, updates);
  }

  /** 立即执行一次（不改变调度状态）。 */
  async runNow(taskId: string): Promise<Record<string, unknown>> {
    const task = this.getTask(taskId);
    if (!task) return { ok: false, error: "任务不存在" };
    const run = runService.createRun({
      trigger: "schedule",
      taskId,
      scheduledFor: utcNow(),
      status: "queued",
    });
    if (!run) return { ok: false, error: "运行幂等冲突" };
    return { ok: true, run_id: run.id };
  }

  /** 扫描并补跑错过的定时任务。 */
  rescueMissedRuns(since?: Date): Record<string, unknown> {
    const cutoff = since ?? new Date();
    const db = getDb();
    const rows = db
      .prepare(
        "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at < ?",
      )
      .all(cutoff.toISOString()) as ScheduledTaskRow[];
    const rescued: Array<Record<string, unknown>> = [];
    for (const row of rows) {
      const task = this.toOut(row);
      const scheduledFor = task.next_run_at ?? utcNow();
      const existing = runService.getByTaskSlot(task.id, scheduledFor);
      if (existing) {
        rescued.push({ task_id: task.id, scheduled_for: scheduledFor, status: existing.status });
        continue;
      }
      const run = runService.createRun({
        trigger: "schedule",
        taskId: task.id,
        scheduledFor,
        status: "queued",
      });
      if (run) {
        rescued.push({ task_id: task.id, scheduled_for: scheduledFor, run_id: run.id });
      }
    }
    return { rescued: rescued.length, items: rescued };
  }

  /** 健康状态。 */
  health(): Record<string, unknown> {
    const db = getDb();
    const lockRow = db
      .prepare("SELECT COUNT(*) AS c FROM system_locks")
      .get() as { c: number };
    return {
      running: this.running,
      enabled: this.s.scheduler_enabled,
      tasks: this.listTasks().length,
      active_tasks: this.listTasks(true).length,
      locks: lockRow?.c ?? 0,
      owner: this.ownerId,
      max_concurrent: this.s.schedule_max_concurrent,
    };
  }

  private toOut(r: ScheduledTaskRow): ScheduledTaskOut {
    return {
      id: r.id,
      name: r.name,
      prompt: r.prompt,
      mode: r.mode,
      plan_first: Boolean(r.plan_first),
      team_id: r.team_id,
      skills: safeParse<string[]>(r.skills_json, []),
      enable: safeParse<Record<string, unknown>>(r.enable_json, {}),
      schedule_kind: r.schedule_kind,
      cron_expr: r.cron_expr,
      interval_seconds: r.interval_seconds,
      rrule_expr: r.rrule_expr,
      timezone: r.timezone,
      enabled: Boolean(r.enabled),
      allow_unattended_tools: Boolean(r.allow_unattended_tools),
      allow_dangerous_tools: Boolean(r.allow_dangerous_tools),
      daily_run_limit: r.daily_run_limit,
      next_run_at: r.next_run_at,
      last_run_at: r.last_run_at,
      last_status: r.last_status,
      last_error: r.last_error,
      run_count: r.run_count,
      consecutive_failures: r.consecutive_failures,
      backoff_until: r.backoff_until,
      delivery: safeParse<Record<string, unknown>>(r.delivery_json, {}),
      created_at: r.created_at,
      updated_at: r.updated_at,
    };
  }
}

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** 全局单例。 */
export const schedulerService = new SchedulerService();

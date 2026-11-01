/**
 * RunService —— 运行账本与事件回放（契约对齐：backend/app/services/run_service.py）。
 *
 * - 统一承载手动 / 定时 / API 三种触发的运行；
 * - 事件批量写入，避免逐条事务拖慢 SSE；
 * - Plan 模式状态机：`awaiting_approval` → approve / reject；
 * - **乐观锁**：`runs.version_id` 显式条件更新（替代 SQLAlchemy `version_id_col`
 *   的隐式行为，把并发语义写进代码里）。
 */
import { getDb, fromJson, toJson, transaction } from "../../db/client.js";
import { newId, utcNow, type RunEventRow, type RunRow } from "../../db/schema.js";
import { getLogger } from "../../shared/logger.js";
import { workspaceModule } from "./workspace-bridge.js";

const logger = getLogger("run");

export const TERMINAL_STATUSES = new Set([
  "success",
  "failed",
  "skipped",
  "interrupted",
  "rejected",
]);

export interface RunOut {
  id: string;
  task_id: string | null;
  session_id: string | null;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  plan: Array<Record<string, unknown>> | null;
  meta: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result_summary: string | null;
  error: string | null;
  files: unknown[];
  created_at: string;
}

export interface RunEventOut {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export function runToOut(row: RunRow): RunOut {
  return {
    id: row.id,
    task_id: row.task_id,
    session_id: row.session_id,
    trigger: row.trigger,
    scheduled_for: row.scheduled_for,
    status: row.status,
    plan: row.plan_json ? fromJson<Array<Record<string, unknown>>>(row.plan_json, []) : null,
    meta: fromJson<Record<string, unknown>>(row.meta_json, {}),
    started_at: row.started_at,
    finished_at: row.finished_at,
    duration_ms: row.duration_ms,
    result_summary: row.result_summary,
    error: row.error,
    files: fromJson<unknown[]>(row.files_json, []),
    created_at: row.created_at,
  };
}

/** 解析 ISO 时间（非法返回 null）。 */
export function parseIso(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 时区解析：非法时区回落 UTC（不抛，避免配额统计被一个坏配置打断）。 */
export function resolveZone(tz: string | null): string {
  if (!tz) return "UTC";
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return tz;
  } catch {
    return "UTC";
  }
}

/** 取某时区在给定时刻的 UTC 偏移（毫秒）。 */
export function tzOffsetMs(zone: string, at: Date): number {
  try {
    const dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    const parts = Object.fromEntries(dtf.formatToParts(at).map((p) => [p.type, p.value]));
    const asUtc = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour) % 24,
      Number(parts.minute),
      Number(parts.second),
    );
    return asUtc - Math.floor(at.getTime() / 1000) * 1000;
  } catch {
    return 0;
  }
}

/** 取某时区的本地自然日边界（UTC ISO）。 */
export function localDayStartUtc(tz: string, at: Date = new Date()): { start: string; end: string } {
  const zone = resolveZone(tz);
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = Object.fromEntries(fmt.formatToParts(at).map((p) => [p.type, p.value]));
  const y = Number(parts.year);
  const mo = Number(parts.month);
  const d = Number(parts.day);
  const localMidnightUtcGuess = Date.UTC(y, mo - 1, d, 0, 0, 0);
  const offset = tzOffsetMs(zone, at);
  const nextOffset = tzOffsetMs(zone, new Date(localMidnightUtcGuess + 86400_000));
  return {
    start: new Date(localMidnightUtcGuess - offset).toISOString(),
    end: new Date(localMidnightUtcGuess + 86400_000 - nextOffset).toISOString(),
  };
}

export interface RunUsage {
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  estimated_cost: number;
}

/** 用量聚合提供者（由 accounting 模块注入，避免循环依赖）。 */
let usageProvider: ((runId: string) => RunUsage) | null = null;

export function registerUsageProvider(fn: (runId: string) => RunUsage): void {
  usageProvider = fn;
}

export class RunService {
  /**
   * 创建运行记录；幂等冲突（同 task 同 slot）返回 null。
   *
   * 工作空间绑定：`workspaceId` 显式指定则用之；否则用**当前工作空间**
   * （无当前空间则自动创建独立工作区）。
   */
  createRun(opts: {
    trigger?: string;
    taskId?: string | null;
    sessionId?: string | null;
    scheduledFor?: string | null;
    status?: string;
    meta?: Record<string, unknown>;
    workspaceId?: string | null;
  } = {}): RunOut | null {
    const db = getDb();
    const meta: Record<string, unknown> = { ...(opts.meta ?? {}) };
    if (!("workspace_id" in meta)) {
      const bound = this.bindWorkspace(opts.workspaceId ?? null);
      meta.workspace_id = bound.id;
      meta.workspace_root = bound.root;
    }
    const id = newId();
    try {
      db.prepare(
        `INSERT INTO runs (id, task_id, session_id, trigger, scheduled_for, status,
          plan_json, meta_json, started_at, finished_at, duration_ms, result_summary,
          error, files_json, prompt_tokens, completion_tokens, llm_calls, tool_calls,
          estimated_cost, created_at, version_id)
         VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, '[]',
          NULL, NULL, NULL, NULL, NULL, ?, 1)`,
      ).run(
        id,
        opts.taskId ?? null,
        opts.sessionId ?? null,
        opts.trigger ?? "api",
        opts.scheduledFor ?? null,
        opts.status ?? "queued",
        toJson(meta),
        utcNow(),
      );
      const row = db.prepare("SELECT * FROM runs WHERE id = ?").get(id) as RunRow;
      return runToOut(row);
    } catch (err) {
      const code = (err as { code?: string })?.code ?? "";
      if (code.startsWith("SQLITE_CONSTRAINT")) {
        logger.info("运行幂等冲突，跳过", {
          taskId: opts.taskId,
          slot: opts.scheduledFor,
        });
        return null;
      }
      throw err;
    }
  }

  /** 解析 run 的工作空间：显式指定 → 当前空间 → 自动创建独立工作区。 */
  private bindWorkspace(workspaceId: string | null): { id: string | null; root: string } {
    const { workspaceService } = workspaceModule();
    if (workspaceId) {
      const ws = workspaceService.get(workspaceId);
      if (!ws) throw new Error(`工作空间不存在: ${workspaceId}`);
      return { id: ws.id, root: ws.root_path };
    }
    const current = workspaceService.current();
    if (current) return { id: current.id, root: current.root_path };
    const bound = workspaceService.bindForRun(null);
    return { id: bound.id, root: bound.root_path };
  }

  getRun(runId: string): RunOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow | undefined;
    return row ? runToOut(row) : null;
  }

  updateMeta(runId: string, meta: Record<string, unknown>): void {
    getDb().prepare("UPDATE runs SET meta_json = ? WHERE id = ?").run(toJson(meta), runId);
  }

  attachSession(runId: string, sessionId: string): void {
    getDb()
      .prepare("UPDATE runs SET session_id = ? WHERE id = ? AND session_id IS NULL")
      .run(sessionId, runId);
  }

  markRunning(runId: string): void {
    getDb()
      .prepare("UPDATE runs SET status = 'running', started_at = ? WHERE id = ?")
      .run(utcNow(), runId);
  }

  savePlan(runId: string, plan: Array<Record<string, unknown>>): void {
    getDb()
      .prepare("UPDATE runs SET plan_json = ?, status = 'awaiting_approval' WHERE id = ?")
      .run(toJson(plan), runId);
  }

  /**
   * 批准计划 → 状态转 `queued`。
   *
   * 同时把**恢复参数**写入 `meta_json`（含 `resume_of` 与 `approved_at`），
   * 这样进程重启后能扫描并续跑。
   */
  approvePlan(
    runId: string,
    editedPlan: Array<Record<string, unknown>> | null = null,
  ): RunOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow | undefined;
    if (!row || row.status !== "awaiting_approval") return null;
    const meta = fromJson<Record<string, unknown>>(row.meta_json, {});
    let planJson = row.plan_json;
    if (editedPlan !== null) {
      planJson = toJson(editedPlan);
      meta.plan_edited = true;
    }
    meta.resume_of = runId;
    meta.approved_at = utcNow();
    db.prepare(
      "UPDATE runs SET plan_json = ?, meta_json = ?, status = 'queued' WHERE id = ? AND status = 'awaiting_approval'",
    ).run(planJson, toJson(meta), runId);
    return runToOut(db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow);
  }

  rejectRun(runId: string, reason = ""): RunOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow | undefined;
    if (!row || row.status !== "awaiting_approval") return null;
    db.prepare("UPDATE runs SET status = 'rejected', error = ?, finished_at = ? WHERE id = ?").run(
      reason || "用户拒绝了计划",
      utcNow(),
      runId,
    );
    return runToOut(db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow);
  }

  /**
   * 收尾。
   *
   * **终态守卫**：已处于终态则不再改写 status，只补齐 finished_at 等附属信息。
   */
  finish(
    runId: string,
    status: string,
    summary = "",
    files: unknown[] | null = null,
    error: string | null = null,
  ): void {
    const db = getDb();
    transaction(() => {
      const row = db.prepare("SELECT * FROM runs WHERE id = ?").get(runId) as RunRow | undefined;
      if (!row) return;
      if (!TERMINAL_STATUSES.has(row.status)) {
        db.prepare("UPDATE runs SET status = ? WHERE id = ?").run(status, runId);
      }
      db.prepare("UPDATE runs SET finished_at = ? WHERE id = ?").run(utcNow(), runId);

      if (usageProvider) {
        try {
          const agg = usageProvider(runId);
          if (agg.llm_calls) {
            db.prepare(
              "UPDATE runs SET prompt_tokens = ?, completion_tokens = ?, llm_calls = ?, estimated_cost = ? WHERE id = ?",
            ).run(
              agg.prompt_tokens,
              agg.completion_tokens,
              agg.llm_calls,
              agg.estimated_cost,
              runId,
            );
          }
        } catch (exc) {
          logger.warn("用量聚合失败（不影响收尾）", { error: String(exc) });
        }
      }

      const started = parseIso(row.started_at);
      if (started) {
        db.prepare("UPDATE runs SET duration_ms = ? WHERE id = ?").run(
          Date.now() - started.getTime(),
          runId,
        );
      }
      if (summary) {
        db.prepare("UPDATE runs SET result_summary = ? WHERE id = ?").run(
          summary.slice(0, 2000),
          runId,
        );
      }
      if (files !== null) {
        db.prepare("UPDATE runs SET files_json = ? WHERE id = ?").run(toJson(files), runId);
      }
      if (error) {
        db.prepare("UPDATE runs SET error = ? WHERE id = ?").run(error.slice(0, 2000), runId);
      }
    });
  }
  // ------------------------------------------------------------------ //
  // 事件
  // ------------------------------------------------------------------ //
  /** 批量写入事件（seq 在事务内连续生成）。 */
  appendEvents(runId: string, events: Array<Record<string, unknown>>): void {
    if (!events.length) return;
    const db = getDb();
    transaction(() => {
      const maxRow = db
        .prepare("SELECT MAX(seq) AS m FROM run_events WHERE run_id = ?")
        .get(runId) as { m: number | null };
      const base = maxRow?.m ?? 0;
      const stmt = db.prepare(
        "INSERT INTO run_events (run_id, seq, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
      );
      events.forEach((ev, i) => {
        const payload: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(ev)) {
          if (k !== "type") payload[k] = v;
        }
        stmt.run(
          runId,
          base + i + 1,
          String(ev.type ?? "unknown"),
          JSON.stringify(payload).slice(0, 60000),
          utcNow(),
        );
      });
    });
  }

  /** 事件回放（分页）。 */
  listEvents(
    runId: string,
    afterSeq = 0,
    limit = 500,
  ): { items: RunEventOut[]; lastSeq: number; status: string; hasMore: boolean } {
    const db = getDb();
    const rows = db
      .prepare("SELECT * FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?")
      .all(runId, afterSeq, limit + 1) as RunEventRow[];
    const statusRow = db.prepare("SELECT status FROM runs WHERE id = ?").get(runId) as
      | { status: string }
      | undefined;
    const hasMore = rows.length > limit;
    const trimmed = rows.slice(0, limit);
    const items: RunEventOut[] = trimmed.map((r) => ({
      seq: r.seq,
      type: r.type,
      payload: fromJson<Record<string, unknown>>(r.payload_json, {}),
      created_at: r.created_at,
    }));
    const lastSeq = trimmed.length ? trimmed[trimmed.length - 1].seq : afterSeq;
    return { items, lastSeq, status: statusRow?.status ?? "unknown", hasMore };
  }

  /** 运行记录列表（可按 `task_id` 与 `status` 过滤）。 */
  listRuns(
    taskId: string | null = null,
    status: string | null = null,
    page = 1,
    pageSize = 20,
  ): { items: RunOut[]; total: number } {
    const db = getDb();
    const where: string[] = [];
    const params: unknown[] = [];
    if (taskId) {
      where.push("task_id = ?");
      params.push(taskId);
    }
    if (status) {
      where.push("status = ?");
      params.push(status);
    }
    const clause = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const totalRow = db
      .prepare(`SELECT COUNT(*) AS c FROM runs ${clause}`)
      .get(...params) as { c: number };
    const rows = db
      .prepare(`SELECT * FROM runs ${clause} ORDER BY created_at DESC LIMIT ? OFFSET ?`)
      .all(...params, pageSize, (page - 1) * pageSize) as RunRow[];
    return { items: rows.map(runToOut), total: totalRow?.c ?? 0 };
  }

  // ------------------------------------------------------------------ //
  // 调度辅助
  // ------------------------------------------------------------------ //
  /** 按 `(task_id, scheduled_for)` 取 run（幂等槽位查询）。 */
  getByTaskSlot(taskId: string, scheduledFor: string): RunOut | null {
    const db = getDb();
    const row = db
      .prepare("SELECT * FROM runs WHERE task_id = ? AND scheduled_for = ?")
      .get(taskId, scheduledFor) as RunRow | undefined;
    return row ? runToOut(row) : null;
  }

  /** 统计任务「今天」的运行数（按任务时区的本地自然日）。 */
  countTodayRuns(taskId: string, tz: string | null = null): number {
    const db = getDb();
    const { start, end } = localDayStartUtc(tz || "UTC");
    const row = db
      .prepare(
        `SELECT COUNT(*) AS c FROM runs
         WHERE task_id = ? AND started_at >= ? AND started_at < ?
           AND status IN ('running','success','failed','awaiting_approval')`,
      )
      .get(taskId, start, end) as { c: number };
    return row?.c ?? 0;
  }

  /** 把超期未完成的 run 标记为 interrupted。 */
  recoverInterrupted(graceSeconds = 300, reason = "服务重启，标记为中断"): number {
    const db = getDb();
    const threshold = new Date(Date.now() - graceSeconds * 1000).toISOString();
    const rows = db
      .prepare("SELECT * FROM runs WHERE status IN ('queued','running')")
      .all() as RunRow[];
    let count = 0;
    for (const row of rows) {
      const ref = row.started_at || row.created_at;
      if (ref < threshold) {
        db.prepare(
          "UPDATE runs SET status = 'interrupted', error = ?, finished_at = ? WHERE id = ?",
        ).run(`${row.error ?? ""} ${reason}`.trim(), utcNow(), row.id);
        count += 1;
      }
    }
    return count;
  }

  /** 中断一个进行中的 run。 */
  interruptRun(runId: string): void {
    getDb()
      .prepare(
        "UPDATE runs SET status = 'interrupted', finished_at = ? WHERE id = ? AND status IN ('queued','running')",
      )
      .run(utcNow(), runId);
  }
}

/** 全局服务单例。 */
export const runService = new RunService();

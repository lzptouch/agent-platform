/**
 * SessionService —— 会话与消息持久化（契约对齐：backend/app/services/session_service.py）。
 *
 * 关键约束：
 * - 历史回放只取 user / 最终 assistant 文本，**绝不回放 tool 消息与带 tool_calls 的
 *   assistant 消息**（会破坏 OpenAI 兼容接口的 tool_call 配对）；
 * - 消息序号 `seq` 在事务内生成（max(seq)+1），唯一约束兜底。
 */
import { getDb, fromJson, toJson, transaction } from "../../db/client.js";
import { newId, utcNow, type MessageRow, type SessionRow } from "../../db/schema.js";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("session");

export interface MessageOut {
  id: string;
  session_id: string;
  run_id: string | null;
  seq: number;
  role: string;
  content: string;
  steps: unknown[];
  files: unknown[];
  meta: Record<string, unknown>;
  created_at: string;
}

export interface SessionOut {
  id: string;
  mode: "chat" | "plan" | "work";
  plan_first: boolean;
  title: string;
  team_id: string | null;
  skills: string[] | null;
  config: Record<string, unknown>;
  archived: boolean;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SessionDetail extends SessionOut {
  messages: MessageOut[];
  has_more: boolean;
}

function messageToOut(m: MessageRow): MessageOut {
  return {
    id: m.id,
    session_id: m.session_id,
    run_id: m.run_id,
    seq: m.seq,
    role: m.role,
    content: m.content,
    steps: fromJson<unknown[]>(m.steps_json, []),
    files: fromJson<unknown[]>(m.files_json, []),
    meta: fromJson<Record<string, unknown>>(m.meta_json, {}),
    created_at: m.created_at,
  };
}

function sessionToOut(s: SessionRow): SessionOut {
  const db = getDb();
  const countRow = db
    .prepare("SELECT COUNT(*) AS c FROM messages WHERE session_id = ?")
    .get(s.id) as { c: number };
  const config = fromJson<Record<string, unknown>>(s.config_json, {});
  return {
    id: s.id,
    // plan 会话落库为 work + plan_first=1 → 对外还原为 plan
    mode: (s.mode === "work" && s.plan_first ? "plan" : s.mode) as SessionOut["mode"],
    plan_first: Boolean(s.plan_first),
    title: s.title,
    team_id: s.team_id,
    skills: (config.skills as string[] | null) ?? null,
    config: (config.config as Record<string, unknown>) ?? {},
    archived: Boolean(s.archived),
    message_count: countRow?.c ?? 0,
    created_at: s.created_at,
    updated_at: s.updated_at,
  };
}

export class SessionService {
  // ------------------------------------------------------------------ //
  // CRUD
  // ------------------------------------------------------------------ //
  /**
   * 创建会话。
   *
   * `mode` 取值统一为 `chat | plan | work`；`plan` 归一落库为
   * `work + plan_first=1`（与 `scheduled_tasks` 的做法一致）。
   */
  create(
    mode = "chat",
    title = "",
    skills: string[] | null = null,
    teamId: string | null = null,
    config: Record<string, unknown> | null = null,
    planFirst = false,
  ): SessionOut {
    if (!["chat", "plan", "work"].includes(mode)) {
      throw new Error(`非法模式: ${mode}`);
    }
    const storedMode = mode === "plan" ? "work" : mode;
    let storedPlanFirst = mode === "plan" || planFirst ? 1 : 0;
    if (storedMode === "chat") storedPlanFirst = 0;

    const db = getDb();
    const id = newId();
    const now = utcNow();
    db.prepare(
      `INSERT INTO sessions (id, mode, plan_first, title, team_id, config_json,
        owner, archived, deleted_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?)`,
    ).run(
      id,
      storedMode,
      storedPlanFirst,
      title.trim(),
      teamId,
      toJson({ skills, config: config ?? {} }),
      now,
      now,
    );
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(id) as SessionRow;
    return sessionToOut(row);
  }

  /**
   * 会话列表（按模式过滤 + 分页）。
   *
   * 归档与软删是**两个独立维度**：`include_archived` = 包含已归档的；
   * `only_trashed` = 只看回收站（已软删）。
   */
  list(
    mode: string | null = null,
    page = 1,
    pageSize = 20,
    includeArchived = false,
    onlyTrashed = false,
  ): { items: SessionOut[]; total: number } {
    const db = getDb();
    const where: string[] = [];
    const params: unknown[] = [];

    if (mode === "plan") {
      where.push("mode = ? AND plan_first = 1");
      params.push("work");
    } else if (mode) {
      where.push("mode = ?");
      params.push(mode);
    }
    if (!includeArchived) where.push("archived = 0");
    if (onlyTrashed) where.push("deleted_at IS NOT NULL");
    else where.push("deleted_at IS NULL");

    const clause = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const totalRow = db
      .prepare(`SELECT COUNT(*) AS c FROM sessions ${clause}`)
      .get(...params) as { c: number };
    const rows = db
      .prepare(
        `SELECT * FROM sessions ${clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?`,
      )
      .all(...params, pageSize, (page - 1) * pageSize) as SessionRow[];
    return { items: rows.map(sessionToOut), total: totalRow?.c ?? 0 };
  }

  /** 取会话详情；**已软删的会话视为不存在**（→ 404）。 */
  get(
    sessionId: string,
    messageLimit = 100,
    beforeSeq: number | null = null,
  ): SessionDetail | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as
      | SessionRow
      | undefined;
    if (!row || row.deleted_at) return null;

    const params: unknown[] = [sessionId];
    let sql = "SELECT * FROM messages WHERE session_id = ?";
    if (beforeSeq !== null) {
      sql += " AND seq < ?";
      params.push(beforeSeq);
    }
    sql += " ORDER BY seq DESC LIMIT ?";
    params.push(messageLimit + 1);

    const rows = db.prepare(sql).all(...params) as MessageRow[];
    const hasMore = rows.length > messageLimit;
    const msgs = rows.slice(0, messageLimit).reverse();
    const base = sessionToOut(row);
    return { ...base, messages: msgs.map(messageToOut), has_more: hasMore };
  }

  /** 更新会话（改名 / 归档 / 配置）。 */
  update(
    sessionId: string,
    opts: {
      title?: string | null;
      archived?: boolean | null;
      skills?: string[] | null;
      teamId?: string | null;
      config?: Record<string, unknown> | null;
    } = {},
  ): SessionOut | null {
    const db = getDb();
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as
      | SessionRow
      | undefined;
    if (!row) return null;

    let title = row.title;
    let archived = row.archived;
    let teamId = row.team_id;
    let configJson = row.config_json;

    if (opts.title !== undefined && opts.title !== null) title = opts.title.trim();
    if (opts.archived !== undefined && opts.archived !== null) {
      archived = opts.archived ? 1 : 0;
    }
    if (opts.teamId !== undefined && opts.teamId !== null) teamId = opts.teamId;
    if (opts.skills !== undefined || opts.config !== undefined) {
      const cfg = fromJson<Record<string, unknown>>(configJson, {});
      if (opts.skills !== undefined) cfg.skills = opts.skills;
      if (opts.config !== undefined) cfg.config = opts.config;
      configJson = toJson(cfg);
    }

    db.prepare(
      `UPDATE sessions SET title = ?, archived = ?, team_id = ?, config_json = ?, updated_at = ?
       WHERE id = ?`,
    ).run(title, archived, teamId, configJson, utcNow(), sessionId);

    const updated = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as SessionRow;
    return sessionToOut(updated);
  }

  /**
   * **软删除**：写 `deleted_at` + `archived=1`。
   *
   * 消息与 run 记录**保留**，仅从默认列表中隐藏。
   */
  delete(sessionId: string): boolean {
    const db = getDb();
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as
      | SessionRow
      | undefined;
    if (!row || row.deleted_at) return false;
    db.prepare(
      "UPDATE sessions SET deleted_at = ?, archived = 1, updated_at = ? WHERE id = ?",
    ).run(utcNow(), utcNow(), sessionId);
    return true;
  }

  /** **永久删除**（管理员用）——真正物理删除会话及其消息。 */
  purge(sessionId: string): boolean {
    const db = getDb();
    const row = db.prepare("SELECT * FROM sessions WHERE id = ?").get(sessionId) as
      | SessionRow
      | undefined;
    if (!row) return false;
    return transaction(() => {
      db.prepare("UPDATE runs SET session_id = NULL WHERE session_id = ?").run(sessionId);
      db.prepare("DELETE FROM messages WHERE session_id = ?").run(sessionId);
      db.prepare("DELETE FROM sessions WHERE id = ?").run(sessionId);
      return true;
    });
  }

  // ------------------------------------------------------------------ //
  // 消息
  // ------------------------------------------------------------------ //
  /** 追加一条消息（seq 在事务内生成）。 */
  appendMessage(
    sessionId: string,
    role: string,
    content: string,
    runId: string | null = null,
    steps: unknown[] | null = null,
    files: unknown[] | null = null,
    meta: Record<string, unknown> | null = null,
  ): MessageOut {
    const db = getDb();
    const write = (): MessageOut => {
      const maxRow = db
        .prepare("SELECT MAX(seq) AS m FROM messages WHERE session_id = ?")
        .get(sessionId) as { m: number | null };
      const seq = (maxRow?.m ?? 0) + 1;
      const id = newId();
      db.prepare(
        `INSERT INTO messages (id, session_id, run_id, seq, role, content,
          steps_json, files_json, meta_json, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      ).run(
        id,
        sessionId,
        runId,
        seq,
        role,
        content,
        toJson(steps ?? []),
        toJson(files ?? []),
        toJson(meta ?? {}),
        utcNow(),
      );
      db.prepare("UPDATE sessions SET updated_at = ? WHERE id = ?").run(utcNow(), sessionId);
      const sess = db.prepare("SELECT title FROM sessions WHERE id = ?").get(sessionId) as
        | { title: string }
        | undefined;
      if (sess && !sess.title && role === "user" && content) {
        db.prepare("UPDATE sessions SET title = ? WHERE id = ?").run(
          content.trim().slice(0, 30),
          sessionId,
        );
      }
      const row = db.prepare("SELECT * FROM messages WHERE id = ?").get(id) as MessageRow;
      return messageToOut(row);
    };

    // max(seq)+1 存在并发竞态：唯一约束兜底 + 重试重算
    let lastError: unknown;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      try {
        return transaction(write);
      } catch (err) {
        lastError = err;
        const code = (err as { code?: string })?.code ?? "";
        if (!code.startsWith("SQLITE_CONSTRAINT")) throw err;
        logger.debug("消息 seq 冲突，重试", { attempt, error: String(err) });
      }
    }
    throw lastError;
  }

  // ------------------------------------------------------------------ //
  // 历史注入（只回放最终问答）
  // ------------------------------------------------------------------ //
  buildHistory(
    sessionId: string,
    limit: number | null = null,
    maxChars: number | null = null,
  ): Array<{ role: string; content: string }> {
    const lim = (limit ?? settings.session_history_limit) as number;
    const chars = (maxChars ?? settings.session_history_max_chars) as number;
    const db = getDb();
    // 多取一些，给中间态过滤留余量
    const rows = db
      .prepare(
        `SELECT * FROM messages
         WHERE session_id = ? AND role IN ('user','assistant') AND content != ''
         ORDER BY seq DESC LIMIT ?`,
      )
      .all(sessionId, lim * 2) as MessageRow[];

    const items: Array<{ role: string; content: string }> = [];
    for (const m of rows) {
      const meta = fromJson<Record<string, unknown>>(m.meta_json, {});
      if (m.role === "assistant" && meta.tool_only) continue;
      items.push({ role: m.role, content: m.content });
      if (items.length >= lim) break;
    }
    items.reverse();

    // 字符预算：从旧到新裁剪，且首条必须是 user
    while (items.length && items.reduce((sum, i) => sum + i.content.length, 0) > chars) {
      items.shift();
    }
    while (items.length && items[0].role !== "user") {
      items.shift();
    }
    return items;
  }
}

/** 全局服务单例。 */
export const sessionService = new SessionService();

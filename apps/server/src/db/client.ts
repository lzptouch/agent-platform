/**
 * SQLite 连接层（来源：backend/app/db/base.py）。
 *
 * 关键语义（逐条对齐）：
 * - `journal_mode=WAL`（写前日志，提升并发读）；
 * - `synchronous=NORMAL`；
 * - `foreign_keys=ON`（**必须**，否则外键约束不生效 → 与 Python 行为不一致）；
 * - `busy_timeout`（写锁等待）；
 * - **写锁重试**（50/100/200ms 退避）：SQLite 单写者模型下高并发写会 `SQLITE_BUSY`；
 * - **乐观锁**：`runs.version_id` 显式 `WHERE version_id = ?`（替代 SQLAlchemy
 *   `version_id_col` 的隐式行为，把并发语义写进代码里）。
 */
import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { settings, type Settings } from "../shared/config.js";
import { getLogger } from "../shared/logger.js";
import { loadNativeBinding } from "./native.js";

const logger = getLogger("db");

export type Db = Database.Database;

/** 从 `sqlite:///abs/path` 解析出文件路径。 */
export function parseSqlitePath(url: string): string {
  const m = /^sqlite:\/\/\/(.*)$/.exec(url);
  if (m) return m[1];
  if (url === ":memory:" || url.startsWith("file:")) return url;
  return url;
}

let dbInstance: Db | null = null;
let dbPath: string | null = null;

/** 打开数据库并应用 PRAGMA。 */
export function openDatabase(filePath: string): Db {
  if (filePath !== ":memory:" && !filePath.startsWith("file:")) {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  }
  // **双 ABI 加载**（design/16 R5）：显式传入与当前运行时匹配的原生 addon，
  // 避免 Electron（ABI 130）与 Node（ABI 137）共用一份 node_modules 时冲突。
  const db = new Database(filePath, {
    nativeBinding: loadNativeBinding() as never,
  });
  db.pragma("journal_mode = WAL");
  db.pragma("synchronous = NORMAL");
  db.pragma("foreign_keys = ON");
  db.pragma("busy_timeout = 5000");
  return db;
}

/** 初始化连接（幂等）。 */
export function initDb(s: Settings = settings): Db {
  if (dbInstance) return dbInstance;
  const file = parseSqlitePath(s.database_url_abs);
  dbPath = file;
  dbInstance = openDatabase(file);
  logger.info("数据库已连接", { file, url: s.database_url_abs });
  return dbInstance;
}

/** 取得当前连接（未初始化则初始化）。 */
export function getDb(): Db {
  return dbInstance ?? initDb();
}

/** 关闭连接并复位（测试用）。 */
export function resetDb(): void {
  try {
    dbInstance?.close();
  } catch {
    // 忽略
  }
  dbInstance = null;
  dbPath = null;
}

/** 当前数据库文件路径（未初始化为 null）。 */
export function currentDbPath(): string | null {
  return dbPath;
}

/**
 * 写锁重试（SQLite 单写者）。
 *
 * `SQLITE_BUSY` / `SQLITE_LOCKED` 在高并发写（调度器 + Agent + 事件落库）下
 * 会出现；Python 侧靠 SQLAlchemy 的连接池重试，Node 侧显式实现。
 */
const BUSY_CODES = new Set(["SQLITE_BUSY", "SQLITE_LOCKED"]);
const BACKOFF_MS = [50, 100, 200];

/** 在写锁冲突时按 50/100/200ms 退避重试。 */
export function withWriteRetry<T>(fn: () => T): T {
  let lastError: unknown;
  for (let attempt = 0; attempt <= BACKOFF_MS.length; attempt += 1) {
    try {
      return fn();
    } catch (err) {
      const code = (err as { code?: string })?.code ?? "";
      lastError = err;
      if (!BUSY_CODES.has(code) || attempt === BACKOFF_MS.length) throw err;
      const delay = BACKOFF_MS[attempt];
      // 同步退避（better-sqlite3 是同步 API）
      const until = Date.now() + delay;
      while (Date.now() < until) {
        /* 忙等（退避窗口极短） */
      }
    }
  }
  throw lastError;
}

/** 在事务中执行（写锁重试包裹）。 */
export function transaction<T>(fn: () => T): T {
  const db = getDb();
  return withWriteRetry(() => db.transaction(fn)());
}

/** JSON 序列化助手（与 Python `json.dumps(..., ensure_ascii=False)` 对齐）。 */
export function toJson(value: unknown): string {
  return JSON.stringify(value ?? null);
}

/** JSON 反序列化助手（容错：非法 JSON 返回默认值）。 */
export function fromJson<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw);
    return (parsed ?? fallback) as T;
  } catch {
    return fallback;
  }
}

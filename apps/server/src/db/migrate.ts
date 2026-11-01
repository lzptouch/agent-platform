/**
 * 迁移器（来源：backend/scripts/migrate.py + app/db/migrations/）。
 *
 * 语义：
 * - 自建 `__migrations` 表记录已应用版本（不引第三方 runner）；
 * - **旧库检测**：无 `__migrations` 但存在 `sessions` → 判定为 Python 版遗留库；
 * - **自动备份**：判定旧库时先复制 `app.db.bak-<ts>`（保留最近 3 份）；
 * - 基线一次建到最终态（等价 12 个 Alembic 迁移的净效果）。
 */
import fs from "node:fs";
import path from "node:path";
import { BASELINE_SQL } from "./baseline-sql.js";
import { getDb, parseSqlitePath } from "./client.js";
import { getLogger } from "../shared/logger.js";
import { settings, type Settings } from "../shared/config.js";

const logger = getLogger("db.migrate");

const MIGRATION_TABLE = "__migrations";

/** 备份保留份数（与 design §10.5 一致）。 */
const BACKUP_KEEP = 3;

export interface MigrationResult {
  /** 是否为 Python 版遗留库 */
  legacy: boolean;
  /** 备份文件路径（若发生备份） */
  backupPath: string | null;
  /** 已应用的迁移版本 */
  applied: string[];
  /** 是否创建了全新库 */
  fresh: boolean;
}

function tableExists(db: ReturnType<typeof getDb>, name: string): boolean {
  const row = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
    .get(name);
  return Boolean(row);
}

function ensureMigrationTable(db: ReturnType<typeof getDb>): void {
  db.exec(`CREATE TABLE IF NOT EXISTS ${MIGRATION_TABLE} (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
  )`);
}

function listApplied(db: ReturnType<typeof getDb>): string[] {
  ensureMigrationTable(db);
  const rows = db
    .prepare(`SELECT version FROM ${MIGRATION_TABLE} ORDER BY version`)
    .all() as Array<{ version: string }>;
  return rows.map((r) => r.version);
}

/** 备份数据库文件（保留最近 `BACKUP_KEEP` 份）。 */
export function backupDatabase(file: string): string | null {
  if (file === ":memory:" || file.startsWith("file:")) return null;
  if (!fs.existsSync(file)) return null;
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const target = `${file}.bak-${ts}`;
  try {
    fs.copyFileSync(file, target);
    // 顺带备份 WAL / SHM（避免恢复后丢已提交事务）
    for (const suffix of ["-wal", "-shm"]) {
      const side = `${file}${suffix}`;
      if (fs.existsSync(side)) fs.copyFileSync(side, `${target}${suffix}`);
    }
  } catch (err) {
    logger.error("数据库备份失败", { error: String(err) });
    return null;
  }
  pruneBackups(file);
  logger.info("数据库已备份", { target });
  return target;
}

function pruneBackups(file: string): void {
  const dir = path.dirname(file);
  const base = path.basename(file);
  if (!fs.existsSync(dir)) return;
  const backups = fs
    .readdirSync(dir)
    .filter((f) => f.startsWith(`${base}.bak-`))
    .sort();
  while (backups.length > BACKUP_KEEP) {
    const oldest = backups.shift();
    if (oldest) {
      try {
        fs.rmSync(path.join(dir, oldest), { force: true });
      } catch {
        // 忽略
      }
    }
  }
}

/**
 * 执行迁移。
 *
 * @param s 配置（默认全局 settings）
 */
export function runMigrations(s: Settings = settings): MigrationResult {
  const db = getDb();
  const file = parseSqlitePath(s.database_url_abs);

  // ⚠️ 判定顺序很重要：
  // - `hasSessions` 必须在 `listApplied()`（会**创建** `__migrations` 表）**之前**取；
  // - 「旧库」的判据是「**业务表已存在**但**基线未标记**」——
  //   只看 `__migrations` 表是否存在是不够的（前一次启动失败可能已建出空表）。
  const hasSessions = tableExists(db, "sessions");

  const applied = listApplied(db);
  const hasBaseline = applied.includes("0000_baseline");

  let legacy = false;
  let backupPath: string | null = null;

  if (hasSessions && !hasBaseline) {
    // 旧库（Python 版）→ 备份 → 标记基线
    legacy = true;
    backupPath = backupDatabase(file);
    logger.info("检测到旧版数据库，已备份并标记基线", { file, backupPath });
  }

  const result: MigrationResult = {
    legacy,
    backupPath,
    applied: [...applied],
    fresh: !hasSessions,
  };

  if (hasBaseline) {
    return result;
  }

  if (legacy) {
    // **旧库路径**（design §10.2）：22 张表**已存在** → 只「标记基线」，
    // 再补齐旧库缺失的列（增量）。**不能**重跑基线 DDL（会「表已存在」报错）。
    ensureMigrationTable(db);
    db.prepare(
      `INSERT OR REPLACE INTO ${MIGRATION_TABLE} (version, applied_at) VALUES (?, ?)`,
    ).run("0000_baseline", new Date().toISOString());
    result.applied.push("0000_baseline");
    const added = applyIncrementalColumns(db);
    if (added.length) {
      logger.info("旧库补列完成", { columns: added.length });
    }
    logger.info("旧库已标记基线", { addedColumns: added.length });
    return result;
  }

  // 基线：一次建到最终态
  const statements = BASELINE_SQL.split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.startsWith("--"));

  const applyBaseline = db.transaction(() => {
    for (const stmt of statements) {
      db.exec(stmt);
    }
    db.prepare(
      `INSERT OR REPLACE INTO ${MIGRATION_TABLE} (version, applied_at) VALUES (?, ?)`,
    ).run("0000_baseline", new Date().toISOString());
  });
  applyBaseline();
  result.applied.push("0000_baseline");
  logger.info("基线迁移已应用", {
    statements: statements.length,
    fresh: result.fresh,
  });
  return result;
}

/** 当前库的表清单（用于闸门 3 校验）。 */
export function listTables(): string[] {
  const db = getDb();
  const rows = db
    .prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != ? ORDER BY name",
    )
    .all(MIGRATION_TABLE) as Array<{ name: string }>;
  return rows.map((r) => r.name);
}

/** 某张表的列信息（闸门 3 逐列比对用）。 */
export function tableInfo(table: string): Array<{
  name: string;
  type: string;
  notnull: number;
  dflt_value: string | null;
  pk: number;
}> {
  const db = getDb();
  return db.prepare(`PRAGMA table_info(${table})`).all() as Array<{
    name: string;
    type: string;
    notnull: number;
    dflt_value: string | null;
    pk: number;
  }>;
}

/**
 * 解析基线 DDL → `{ 表名: [{name, type, notnull, dflt}] }`。
 *
 * 只解析 `CREATE TABLE` 块内的列定义行（跳过表级约束）。
 */
function parseBaselineColumns(): Map<string, Array<{ name: string; type: string; notnull: boolean; dflt: string | null }>> {
  const out = new Map<string, Array<{ name: string; type: string; notnull: boolean; dflt: string | null }>>();
  const blocks = BASELINE_SQL.split(/CREATE TABLE /i).slice(1);
  for (const block of blocks) {
    const nameMatch = /^(\w+)\s*\(/.exec(block);
    if (!nameMatch) continue;
    const table = nameMatch[1];
    const body = block.slice(block.indexOf("(") + 1);
    // 取到与表名同层的右括号
    let depth = 1;
    let end = 0;
    for (let i = 0; i < body.length; i += 1) {
      if (body[i] === "(") depth += 1;
      else if (body[i] === ")") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    const columns: Array<{ name: string; type: string; notnull: boolean; dflt: string | null }> = [];
    for (const rawLine of body.slice(0, end).split(/,\s*(?=\n|\s*\w+\s)/)) {
      const line = rawLine.trim().replace(/\n\s*/g, " ");
      if (!line) continue;
      if (/^(PRIMARY KEY|FOREIGN KEY|UNIQUE|CHECK|CONSTRAINT)\b/i.test(line)) continue;
      const m = /^("?\w+"?)\s+([A-Za-z]+(?:\([^)]*\))?)(.*)$/.exec(line);
      if (!m) continue;
      const colName = m[1].replace(/"/g, "");
      const colType = m[2].toUpperCase();
      const rest = m[3] ?? "";
      const notnull = /NOT\s+NULL/i.test(rest);
      const dfltMatch = /DEFAULT\s+('(?:[^']*)'|\S+)/i.exec(rest);
      columns.push({
        name: colName,
        type: colType,
        notnull,
        dflt: dfltMatch ? dfltMatch[1] : null,
      });
    }
    out.set(table, columns);
  }
  return out;
}

/**
 * 补齐旧库缺失的列（**增量迁移**）。
 *
 * 旧库（Python 版）由 12 个 Alembic 迁移演进而来 → 少数后加的列可能缺失
 * （如 `sessions.deleted_at`、`artifacts.url`）。这里逐表比对基线 DDL，
 * 对缺失列执行 `ALTER TABLE ... ADD COLUMN`。
 *
 * ⚠️ **只加列**：不加索引、不改类型、不动数据 —— 与「表名/列名保持一致即可
 * 原地升级」的设计约束一致（design §10.2）。
 */
export function applyIncrementalColumns(
  db: ReturnType<typeof getDb>,
): string[] {
  const added: string[] = [];
  const baseline = parseBaselineColumns();
  for (const [table, columns] of baseline) {
    if (!tableExists(db, table)) continue;
    const existing = new Set(tableInfo(table).map((c) => c.name));
    for (const col of columns) {
      if (existing.has(col.name)) continue;
      const parts = [`ALTER TABLE ${table} ADD COLUMN "${col.name}" ${col.type}`];
      if (col.dflt !== null) parts.push(`DEFAULT ${col.dflt}`);
      if (!col.notnull && col.dflt === null) parts.push("NULL");
      try {
        db.exec(parts.join(" "));
        added.push(`${table}.${col.name}`);
      } catch (err) {
        logger.warn("补列失败", { table, column: col.name, error: String(err) });
      }
    }
  }
  return added;
}

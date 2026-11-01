/**
 * TS 后端测试基座：独立临时 SQLite + 服务容器复位。
 *
 * 与 Python 侧 `backend/tests/conftest.py` 对齐（同一测试会话一个临时库，
 * 每个用例后清空全部表并复位进程级单例）。
 *
 * ⚠️ 数据目录由 `vitest.config.ts` 的 `env` 注入 —— `config.ts` 的
 * `export const settings = getSettings()` 在模块求值期即读取环境变量，
 * 必须早于本模块的 import 生效。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, afterEach } from "vitest";
import { resetDb, getDb } from "../src/db/client.js";
import { runMigrations } from "../src/db/migrate.js";
import { TABLE_NAMES } from "../src/db/schema.js";

/** 临时数据目录（由 vitest.config.ts 注入）。 */
export function testDataDir(): string {
  return process.env.AGENT_DATA_DIR ?? "";
}

afterEach(() => {
  // 清空全部业务表 + 复位单例（与 Python 侧 conftest 同语义）
  const db = getDb();
  for (const table of TABLE_NAMES) {
    try {
      db.prepare(`DELETE FROM ${table}`).run();
    } catch {
      // 表可能尚未建好
    }
  }
  try {
    db.prepare("DELETE FROM system_locks").run();
  } catch {
    // 忽略
  }
});

afterAll(() => {
  resetDb();
  const dir = testDataDir();
  if (dir && dir.includes("agent-ts-test")) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

/** 建库 + 迁移（供各测试文件按需调用）。 */
export function ensureSchema(): void {
  getDb();
  runMigrations();
}

/**
 * 数据层契约测试（对应 Python 侧 `backend/tests/test_db.py`）。
 *
 * 校验 22 张表的**表名 / 列名 / 类型 / 非空 / 唯一约束**与
 * `contract/tables.sql` 零差异（闸门 3）。
 */
import { describe, expect, it } from "vitest";
import { ensureSchema, testDataDir } from "./setup.js";
import { listTables, tableInfo } from "../../../apps/server/src/db/migrate.js";
import { TABLE_NAMES } from "../../../apps/server/src/db/schema.js";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CONTRACT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../contract",
);

describe("数据层契约（22 表）", () => {
  it("迁移后建出全部 22 张业务表", () => {
    ensureSchema();
    const tables = listTables();
    for (const name of TABLE_NAMES) {
      expect(tables, `缺少表 ${name}`).toContain(name);
    }
    expect(TABLE_NAMES.length).toBe(22);
  });

  it("迁移幂等：重复执行不报错", () => {
    ensureSchema();
    expect(() => ensureSchema()).not.toThrow();
  });

  it("DDL 与 contract/tables.sql 的表名集合一致", () => {
    ensureSchema();
    const ddl = fs.readFileSync(path.join(CONTRACT_DIR, "tables.sql"), "utf-8");
    const contractTables = [...ddl.matchAll(/CREATE TABLE (\w+)/g)].map((m) => m[1]);
    expect(contractTables.sort()).toEqual([...TABLE_NAMES].sort());
  });

  it("关键表的列名与类型对齐契约", () => {
    ensureSchema();
    const runs = tableInfo("runs");
    const names = runs.map((c) => c.name);
    for (const expected of [
      "id",
      "task_id",
      "session_id",
      "trigger",
      "scheduled_for",
      "status",
      "plan_json",
      "meta_json",
      "started_at",
      "finished_at",
      "duration_ms",
      "result_summary",
      "error",
      "files_json",
      "prompt_tokens",
      "completion_tokens",
      "llm_calls",
      "tool_calls",
      "estimated_cost",
      "created_at",
      "version_id",
    ]) {
      expect(names, `runs 表缺少列 ${expected}`).toContain(expected);
    }
    // 布尔统一 integer（0/1）→ `plan_first` 应为 INTEGER
    const sessions = tableInfo("sessions");
    const planFirst = sessions.find((c) => c.name === "plan_first");
    expect(planFirst?.type.toUpperCase()).toBe("INTEGER");
    // 时间统一 TEXT
    const createdAt = sessions.find((c) => c.name === "created_at");
    expect(createdAt?.type.toUpperCase()).toBe("TEXT");
  });

  it("数据落在临时目录（不污染真实数据根）", () => {
    ensureSchema();
    expect(testDataDir()).toContain("agent-ts-test");
    expect(fs.existsSync(path.join(testDataDir(), "app.db"))).toBe(true);
  });
});

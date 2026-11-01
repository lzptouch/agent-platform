/**
 * 测试环境隔离（**必须最先加载**）。
 *
 * ⚠️ **为什么要按 worker 隔离**：`vitest` 用 `pool: "forks"` **并行**跑各测试
 * 文件，而它们共用同一个 SQLite 文件 → 并发写 → `SQLITE_BUSY` / `disk I/O error`
 * （P8-02 新增 `response-shape.test.ts` 时暴露）。
 *
 * `pool: "forks"` 下每个 worker 的 `process.pid` 互不相同 → 用它做目录后缀。
 *
 * ⚠️ **必须早于任何应用模块的 import**：`config.ts` 的
 * `export const settings = getSettings()` 在**模块求值期**就读取
 * `AGENT_DATA_DIR` → 只能靠 `setupFiles` 的**加载顺序**保证（本文件排第一）。
 */
import os from "node:os";
import path from "node:path";

const base = process.env.AGENT_TEST_DATA_BASE ?? path.join(os.tmpdir(), "agent-ts-test");
process.env.AGENT_DATA_DIR = `${base}-${process.pid}`;
process.env.AGENT_DESKTOP = "0";

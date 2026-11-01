import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["../../tests/unit/server/**/*.test.ts"],
    globals: false,
    testTimeout: 30_000,
    hookTimeout: 30_000,
    pool: "forks",
    // ⚠️ **顺序有意义**：`env-setup.ts` 必须**先于** `setup.ts` ——
    //    它按 worker（pid）隔离 SQLite 目录，避免并行跑多个测试文件时
    //    共享同一个库 → `SQLITE_BUSY` / `disk I/O error`（P8-02 实测）。
    setupFiles: [
      "../../tests/unit/server/env-setup.ts",
      "../../tests/unit/server/setup.ts",
    ],
  },
});

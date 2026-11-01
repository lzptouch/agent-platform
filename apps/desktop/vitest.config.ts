import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    // 单测已归拢到仓库根 tests/unit/desktop/，裸导入（electron …）与
    // vi.mock("electron") 从那里向上找不到 node_modules → 显式补充模块目录
    modules: [
      "node_modules",
      fileURLToPath(new URL("./node_modules", import.meta.url)),
    ],
  },
  test: {
    environment: "node",
    include: ["../../tests/unit/desktop/**/*.test.ts"],
    reporters: "default",
    passWithNoTests: false,
  },
});

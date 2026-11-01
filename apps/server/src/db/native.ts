/**
 * 原生模块（better-sqlite3）的 **双 ABI 加载器**。
 *
 * **为什么需要（design/16 R5）**：
 * - 桌面壳用 **Electron 33**（内含 Node 20.18 → `NODE_MODULE_VERSION 130`）；
 * - 开发态测试用 **系统 Node**（v22+ → `NODE_MODULE_VERSION 127/137`）；
 * - 二者的原生二进制**ABI 不同**，同一份 `node_modules` 无法同时满足。
 *
 * **做法**：
 * 1. `scripts/rebuild-native.mjs` 分别构建两遍，产物复制到
 *    `apps/server/.native/abi-<ABI>/better_sqlite3.node`；
 * 2. 运行时按 `process.versions.modules` 选择对应 ABI 的二进制；
 * 3. 用 better-sqlite3 v11 的 **`nativeBinding` 选项**显式传入已加载的 addon
 *    → 完全绕开 `bindings` 的路径猜测，**同一份安装同时支持两个运行时**。
 */
import path from "node:path";
import fs from "node:fs";
import { createRequire } from "node:module";
import { SERVICE_ROOT } from "../shared/config.js";

const require_ = createRequire(import.meta.url);

/** 当前运行时的 ABI（`process.versions.modules`）。 */
export function currentAbi(): string {
  return process.versions.modules ?? "0";
}

/** 候选二进制路径（按优先级）。 */
export function candidateBindings(): string[] {
  const abi = currentAbi();
  const pkgDir = path.dirname(require_.resolve("better-sqlite3/package.json"));
  return [
    // ① 双 ABI 产物（scripts/rebuild-native.mjs 生成）—— 首选
    path.join(SERVICE_ROOT, ".native", `abi-${abi}`, "better_sqlite3.node"),
    // ② electron-rebuild 的 ABI 专属目录
    path.join(
      pkgDir,
      "bin",
      `${process.platform}-${process.arch}-${abi}`,
      "better_sqlite3.node",
    ),
    // ③ 通用构建产物（node-gyp 输出）
    path.join(pkgDir, "build", "Release", "better_sqlite3.node"),
    path.join(pkgDir, "build", "Debug", "better_sqlite3.node"),
  ];
}

let cached: unknown = null;

/**
 * 加载与当前运行时 ABI 匹配的原生 addon。
 *
 * 找不到可用二进制时抛出**明确**的错误（含已尝试的路径与所需 ABI），
 * 避免出现「运行时才炸」的静默失败。
 */
export function loadNativeBinding(): unknown {
  if (cached) return cached;
  const tried: string[] = [];
  for (const candidate of candidateBindings()) {
    tried.push(candidate);
    if (!fs.existsSync(candidate)) continue;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      cached = require_(candidate);
      return cached;
    } catch {
      // ABI 不匹配 → 试下一个
    }
  }
  throw new Error(
    `better-sqlite3 原生模块不可用（需要 ABI ${currentAbi()}）。已尝试：\n` +
      tried.map((p) => `  - ${p}`).join("\n") +
      `\n修复：node scripts/rebuild-native.mjs（同时生成 Node 与 Electron 两套 ABI）`,
  );
}

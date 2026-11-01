/** 运行时路径解析。
 *
 * 分两类根（见 doc/design/04 §1）：
 *
 * - ``installDir`` —— 程序根。**打包态** = ``process.resourcesPath``；
 *   **开发态** = 桌面工程根（含 ``package.json`` / ``electron-builder.yml`` 的那一层），
 *   由「自 ``__dirname`` 向上查找工程标记文件」确定，不依赖编译产物层级。
 * - ``userDataDir`` —— 可写数据根（Electron ``app.getPath('userData')``）。
 *
 * 目录约定（2026-11 起 · design/16）：桌面工程位于 ``apps/desktop/``，故开发态
 * - 仓库根 = 工程根上一级（``apps/desktop`` → ``apps`` → 仓库根）；
 * - TS 后端入口 = 仓库根 ``apps/server/dist/main.js``；
 * - 内置 Skill = 仓库根 ``skills/``；
 * - 前端产物 = 仓库根 ``apps/ui/dist``。
 *
 * **改造要点（design/16 §8.2）**：``resolvePython()`` → ``resolveServerEntry()``
 * （后端已由 Python 重写为 TypeScript，与壳共用同一份 Node 运行时）。
 */
import { app } from "electron";
import path from "node:path";
import fs from "node:fs";

export interface Paths {
  installDir: string;
  userDataDir: string;
  dataDir: string;
  logsDir: string;
  configPath: string;
  runStatePath: string;
}

let cached: Paths | null = null;

/** 自当前目录向上查找桌面工程根（含 package.json 且 name=agent-desktop）。 */
function findDesktopRoot(from: string): string {
  let dir = from;
  for (let i = 0; i < 6; i += 1) {
    const pkg = path.join(dir, "package.json");
    if (fs.existsSync(pkg)) {
      try {
        const meta = JSON.parse(fs.readFileSync(pkg, "utf-8")) as { name?: string };
        if (meta.name === "agent-desktop") return dir;
      } catch {
        // 解析失败则继续向上
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  // 兜底：编译产物在 apps/desktop/dist-main/main，工程根应为上两级
  return path.resolve(from, "..", "..");
}

/** 开发态：仓库根（桌面工程在 `apps/desktop/` 下，故上两级）。 */
function repoRootOf(installDir: string): string {
  return path.join(installDir, "..", "..");
}

/** 开发态：前端根（`apps/`）。 */
function appsRootOf(installDir: string): string {
  return path.join(installDir, "..");
}

export function getPaths(): Paths {
  if (cached) return cached;
  const installDir = app.isPackaged
    ? process.resourcesPath
    : findDesktopRoot(__dirname);
  const userDataDir = app.getPath("userData");
  const dataDir = path.join(userDataDir, "data");
  const logsDir = path.join(userDataDir, "logs");
  cached = {
    installDir,
    userDataDir,
    dataDir,
    logsDir,
    configPath: path.join(userDataDir, "config.json"),
    runStatePath: path.join(userDataDir, "run-state.json"),
  };
  for (const dir of [dataDir, logsDir]) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return cached;
}

/**
 * TS 后端入口：打包态 = `resources/server/main.js`，开发态 = `apps/server/dist/main.js`。
 *
 * **改造要点（design/16 §8.2）**：原先此处返回 Python 解释器路径
 * （`resolvePython()`），后端重写为 TypeScript 后由 `utilityProcess.fork()`
 * 直接加载本入口 → **软件只剩一个运行时（Node）**。
 */
export function resolveServerEntry(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "server", "main.js");
  }
  return path.join(repoRootOf(installDir), "apps", "server", "dist", "main.js");
}

/** 内置 Skill 目录：打包态 = `resources/skills`，开发态 = 仓库根 `skills/`。 */
export function resolveSkillsDir(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "skills");
  }
  return path.join(repoRootOf(installDir), "skills");
}

/** 后端工作目录（apps/server/）。 */
export function resolveBackendDir(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "server");
  }
  return path.join(repoRootOf(installDir), "apps", "server");
}

/** 前端产物目录：打包态 = resources/frontend，开发态 = apps/ui/dist。 */
export function resolveFrontendDist(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "frontend");
  }
  return path.join(appsRootOf(installDir), "ui", "dist");
}

/** 启动页：打包态 = resources/frontend/splash.html，开发态 = apps/ui/splash.html。 */
export function resolveSplashPath(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "frontend", "splash.html");
  }
  return path.join(appsRootOf(installDir), "ui", "splash.html");
}

/** 运行时路径解析。
 *
 * 分两类根（见 doc/design/04 §1）：
 *
 * - ``installDir`` —— 程序根。**打包态** = ``process.resourcesPath``；
 *   **开发态** = 桌面工程根（含 ``package.json`` / ``electron-builder.yml`` 的那一层），
 *   由「自 ``__dirname`` 向上查找工程标记文件」确定，不依赖编译产物层级。
 * - ``userDataDir`` —— 可写数据根（Electron ``app.getPath('userData')``）。
 *
 * 历史缺陷（2026-10-27 修复）：开发态曾用 ``path.join(__dirname, "..")`` 当工程根，
 * 而实际运行时 ``__dirname`` 是 ``frontend/desktop/dist-main/main``，导致根目录少了一层 ——
 * sidecar 解释器、前端产物、启动页路径全部错位（应用起不来）。
 *
 * 目录约定（2026-10-28 起）：桌面工程位于 ``frontend/desktop/``，故开发态
 * - 仓库根 = 工程根上两级（``frontend/desktop`` → 仓库根）；
 * - 前端根 = 工程根上一级（``frontend/``，其下是 ``dist/`` 与 ``splash.html``）。
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
  // 兜底：编译产物在 frontend/desktop/dist-main/main，工程根应为上两级
  return path.resolve(from, "..", "..");
}

/** 开发态：仓库根（桌面工程在 `frontend/desktop/` 下，故上两级）。 */
function repoRootOf(installDir: string): string {
  return path.join(installDir, "..", "..");
}

/** 开发态：前端根（`frontend/`）。 */
function frontendRootOf(installDir: string): string {
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

/** 后端可执行文件：打包态 = runtime 内的解释器，开发态 = 仓库 venv。 */
export function resolvePython(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    // 打包产物的运行时布局**随平台而变**（见 scripts/stage-runtime.mjs）：
    //   Windows → runtime/python.exe
    //   POSIX   → runtime/bin/python3
    // 早前这里硬编码 python.exe，macOS/Linux 打包态侧车必然 spawn 失败（ENOENT），
    // 而 spawn 的 error 只进了握手 Promise，没人订阅 → **完全静默**。
    const win = path.join(installDir, "runtime", "python.exe");
    const nix = path.join(installDir, "runtime", "bin", "python3");
    if (fs.existsSync(win)) return win;
    if (fs.existsSync(nix)) return nix;
    return process.platform === "win32" ? win : nix;
  }
  // 开发态：优先 backend/.venv
  const repoRoot = repoRootOf(installDir);
  const win = path.join(repoRoot, "backend", ".venv", "Scripts", "python.exe");
  const nix = path.join(repoRoot, "backend", ".venv", "bin", "python");
  if (fs.existsSync(win)) return win;
  if (fs.existsSync(nix)) return nix;
  return "python";
}

/** 后端工作目录（backend/）。 */
export function resolveBackendDir(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "runtime", "agent");
  }
  return path.join(repoRootOf(installDir), "backend");
}

/** 前端产物目录：打包态 = resources/frontend，开发态 = frontend/dist。 */
export function resolveFrontendDist(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "frontend");
  }
  return path.join(frontendRootOf(installDir), "dist");
}

/** 启动页：打包态 = resources/frontend/splash.html（构建时随前端产物拷贝），开发态 = frontend/splash.html。 */
export function resolveSplashPath(): string {
  const { installDir } = getPaths();
  if (app.isPackaged) {
    return path.join(installDir, "frontend", "splash.html");
  }
  return path.join(frontendRootOf(installDir), "splash.html");
}

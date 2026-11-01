import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

const appState = {
  isPackaged: false,
  resourcesPath: "",
  userData: "",
};

vi.mock("electron", () => ({
  app: {
    get isPackaged() {
      return appState.isPackaged;
    },
    get resourcesPath() {
      return appState.resourcesPath;
    },
    getPath: (name: string) => {
      if (name === "userData") return appState.userData;
      return path.join(appState.userData, name);
    },
  },
}));

import {
  getPaths,
  resolveBackendDir,
  resolveFrontendDist,
  resolveServerEntry,
  resolveSkillsDir,
} from "./paths";

describe("路径解析", () => {
  let tmpRoot = "";

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wb-paths-"));
    appState.isPackaged = false;
    appState.userData = path.join(tmpRoot, "userData");
    appState.resourcesPath = "";
  });

  it("开发态：数据目录落在 userData 下并自动创建", () => {
    const paths = getPaths();
    expect(paths.dataDir.startsWith(appState.userData)).toBe(true);
    expect(fs.existsSync(paths.dataDir)).toBe(true);
    expect(fs.existsSync(paths.logsDir)).toBe(true);
  });

  it("run-state 与 config 路径互相独立", () => {
    const paths = getPaths();
    expect(paths.runStatePath).not.toBe(paths.configPath);
    expect(paths.runStatePath.endsWith("run-state.json")).toBe(true);
  });

  it("开发态：TS 后端入口指向 apps/server/dist/main.js", () => {
    const entry = resolveServerEntry();
    expect(entry.endsWith(path.join("apps", "server", "dist", "main.js"))).toBe(true);
  });

  it("打包态：TS 后端入口指向 resources/server/main.js", async () => {
    // `getPaths()` 会缓存结果 → 打包态需重置模块后再取
    // 打包态的 installDir 取自 `process.resourcesPath`（Electron 注入）
    appState.isPackaged = true;
    appState.resourcesPath = path.join(tmpRoot, "resources");
    (process as unknown as { resourcesPath: string }).resourcesPath =
      appState.resourcesPath;
    vi.resetModules();
    const mod = await import("./paths");
    const entry = mod.resolveServerEntry();
    expect(entry.endsWith(path.join("resources", "server", "main.js"))).toBe(true);
  });

  it("后端工作目录指向仓库 apps/server/", () => {
    expect(resolveBackendDir().endsWith(path.join("apps", "server"))).toBe(true);
  });

  it("内置 Skill 目录指向仓库 skills/", () => {
    expect(resolveSkillsDir().endsWith("skills")).toBe(true);
  });

  it("前端产物目录指向 apps/ui/dist（开发态）", () => {
    expect(resolveFrontendDist().endsWith(path.join("apps", "ui", "dist"))).toBe(true);
  });
});

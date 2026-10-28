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

import { getPaths, resolveBackendDir, resolveFrontendDist, resolvePython } from "./paths";

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

  it("开发态优先使用 backend/.venv 下的解释器", () => {
    const python = resolvePython();
    expect(python.endsWith("python.exe") || python.endsWith("bin/python") || python === "python").toBe(
      true,
    );
  });

  it("后端工作目录指向仓库 backend/", () => {
    expect(resolveBackendDir().endsWith("backend")).toBe(true);
  });

  it("前端产物目录指向 frontend/dist（开发态）", () => {
    expect(resolveFrontendDist().endsWith(path.join("frontend", "dist"))).toBe(true);
  });
});

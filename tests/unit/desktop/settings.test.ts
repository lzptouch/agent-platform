import { beforeEach, describe, expect, it, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const loginItemSettings: Array<{ openAtLogin: boolean }> = [];

vi.mock("electron", () => ({
  app: {
    isPackaged: false,
    setLoginItemSettings: (opts: { openAtLogin: boolean }) => {
      loginItemSettings.push(opts);
    },
  },
}));

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-settings-"));
vi.mock("../../../apps/desktop/src/main/paths", () => ({
  getPaths: () => ({ configPath: path.join(tmpDir, "config.json"), userDataDir: tmpDir }),
}));

import {
  DEFAULT_SETTINGS,
  applyAutoLaunch,
  getSettings,
  resetSettingsCache,
  updateSettings,
} from "../../../apps/desktop/src/main/settings";

describe("壳设置（Boss Key / 开机自启 / 启动最小化）", () => {
  beforeEach(() => {
    loginItemSettings.length = 0;
    resetSettingsCache();
    fs.rmSync(path.join(tmpDir, "config.json"), { force: true });
  });

  it("默认不绑定 Boss Key", () => {
    expect(getSettings().bossKey).toBeNull();
    expect(getSettings().autoLaunch).toBe(false);
    expect(getSettings().startMinimized).toBe(false);
    expect(DEFAULT_SETTINGS.bossKey).toBeNull();
  });

  it("设置可持久化到配置文件", () => {
    updateSettings({ bossKey: "Ctrl+Shift+B", startMinimized: true });
    resetSettingsCache();
    const reloaded = getSettings();
    expect(reloaded.bossKey).toBe("Ctrl+Shift+B");
    expect(reloaded.startMinimized).toBe(true);
    expect(fs.existsSync(path.join(tmpDir, "config.json"))).toBe(true);
  });

  it("配置文件损坏时回落默认值", () => {
    fs.writeFileSync(path.join(tmpDir, "config.json"), "{ not json", "utf-8");
    resetSettingsCache();
    expect(getSettings().bossKey).toBeNull();
  });

  it("开机自启写入系统设置", () => {
    applyAutoLaunch(true);
    expect(loginItemSettings).toHaveLength(1);
    expect(loginItemSettings[0].openAtLogin).toBe(true);
  });
});

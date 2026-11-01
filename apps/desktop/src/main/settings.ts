/** 壳设置（Boss Key / 开机自启 / 启动时最小化到托盘）。
 *
 * 持久化在 ``userData/config.json``（与 `getPaths().configPath` 同一份）。
 *
 * 口径：
 * - **Boss Key 默认不绑定** —— 避免与系统 / 其他软件的快捷键冲突；
 *   用户在设置页显式绑定后才注册，解绑即释放注册。
 * - 开机自启用 Electron 的 ``app.setLoginItemSettings``；启动时最小化到托盘
 *   由主进程在窗口就绪后隐藏窗口实现。
 */
import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

import { getPaths } from "./paths";

export interface ShellSettings {
  /** Boss Key 快捷键（Electron accelerator 形态，如 ``Ctrl+Shift+B``）；null = 未绑定 */
  bossKey: string | null;
  /** 开机自启 */
  autoLaunch: boolean;
  /** 启动时最小化到托盘（不显示主窗口） */
  startMinimized: boolean;
}

export const DEFAULT_SETTINGS: ShellSettings = {
  bossKey: null,
  autoLaunch: false,
  startMinimized: false,
};

let cached: ShellSettings | null = null;

/** 读取设置（文件不存在或损坏时回落默认值）。 */
export function getSettings(): ShellSettings {
  if (cached) return cached;
  try {
    const { configPath } = getPaths();
    if (fs.existsSync(configPath)) {
      const raw = JSON.parse(fs.readFileSync(configPath, "utf-8")) as Partial<ShellSettings>;
      cached = {
        bossKey: typeof raw.bossKey === "string" && raw.bossKey ? raw.bossKey : null,
        autoLaunch: raw.autoLaunch === true,
        startMinimized: raw.startMinimized === true,
      };
      return cached;
    }
  } catch {
    // 读取失败 → 用默认值
  }
  cached = { ...DEFAULT_SETTINGS };
  return cached;
}

/** 写入设置（只落盘被显式改动的字段）。 */
export function updateSettings(patch: Partial<ShellSettings>): ShellSettings {
  const next: ShellSettings = { ...getSettings(), ...patch };
  cached = next;
  try {
    const { configPath } = getPaths();
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify(next, null, 2), "utf-8");
  } catch {
    // 落盘失败不阻断（设置仍在内存中生效）
  }
  return next;
}

/** 应用「开机自启」到操作系统。 */
export function applyAutoLaunch(enabled: boolean): void {
  try {
    app.setLoginItemSettings({
      openAtLogin: enabled,
      // Windows 开发态（未打包）不注册自启项，避免污染开发机
      ...(process.platform === "win32" && !app.isPackaged ? { path: "" } : {}),
    });
  } catch {
    // 平台不支持 → 忽略
  }
}

/** 测试用：清空内存缓存。 */
export function resetSettingsCache(): void {
  cached = null;
}

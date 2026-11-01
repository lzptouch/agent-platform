/** 系统托盘：图标、菜单、角标、点击唤起。 */
import { Menu, Tray, app, nativeImage } from "electron";
import path from "node:path";

import { getPaths } from "./paths";
import { createMainWindow, getMainWindow } from "./window";
import { toggleQuickPanel } from "./quick";

let tray: Tray | null = null;
let badgeText: string | null = null;

export function createTray(): void {
  const { installDir } = getPaths();
  // **D6**：此前 `installDir/build/icon.png` 在**两种形态下都不存在** → 空图标。
  // 打包态：Resources/icon.icns；开发态：<工程根>/resources/icon.png。
  const iconPath = app.isPackaged
    ? path.join(installDir, "icon.icns")
    : path.join(installDir, "resources", "icon.png");
  const icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) {
    console.warn(`[tray] 托盘图标缺失或不可读：${iconPath}`);
  }
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  tray.setToolTip("Agent Desktop");
  refreshMenu();

  // 左键点击 → 直接唤起速记输入窗（对齐 Cherry Studio「点击托盘图标启动」）
  tray.on("click", () => toggleQuickPanel());
}

export function setTrayBadge(text: string | null): void {
  badgeText = text;
  refreshMenu();
}

function refreshMenu(): void {
  if (!tray) return;
  const menu = Menu.buildFromTemplate([
    { label: badgeText ? `任务中 ${badgeText}` : "就绪", enabled: false },
    { type: "separator" },
    { label: "打开主窗口", click: () => showMain() },
    { label: "速记输入", click: () => toggleQuickPanel() },
    { type: "separator" },
    { label: "退出", click: () => app.quit() },
  ]);
  tray.setContextMenu(menu);
}

function showMain(): void {
  const win = getMainWindow();
  if (win) {
    win.show();
    win.focus();
    return;
  }
  // **D5**：窗口不存在（被销毁 / 尚未创建）→ **重建**，而不是静默什么都不做
  createMainWindow();
}

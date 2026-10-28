/** 速记面板（全局热键唤起的迷你输入窗）。

- 无边框、置顶、宽 640×160（运行中任务时顶部显示状态条）；
- 加载主窗口同一应用，路由 ``/workspace?compose=1``；
- 唤起时可自动预填剪贴板文本（只填入输入框，不自动发送）。
 */
import { BrowserWindow, clipboard } from "electron";
import path from "node:path";

import { supervisor } from "./backend";
import { getMainWindow } from "./window";

let quickPanel: BrowserWindow | null = null;

export function toggleQuickPanel(): void {
  if (quickPanel) {
    if (quickPanel.isVisible()) {
      quickPanel.hide();
    } else {
      showQuickPanel();
    }
    return;
  }
  showQuickPanel();
}

function showQuickPanel(): void {
  const handle = supervisor.handle();
  if (!handle) return;

  if (!quickPanel) {
    quickPanel = new BrowserWindow({
      width: 640,
      height: 160,
      frame: false,
      alwaysOnTop: true,
      resizable: false,
      skipTaskbar: true,
      show: false,
      backgroundColor: "#0f1115",
      webPreferences: {
        preload: path.join(__dirname, "..", "..", "dist-preload", "preload", "index.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    quickPanel.on("blur", () => quickPanel?.hide());
    quickPanel.on("closed", () => {
      quickPanel = null;
    });
    const url = `http://127.0.0.1:${handle.port}/workspace?compose=1`;
    void quickPanel.loadURL(url, {
      extraHeaders: `X-Agent-Desktop-Token: ${handle.token}`,
    });
  }

  const clip = clipboard.readText().trim();
  quickPanel.webContents.once("did-finish-load", () => {
    if (clip) {
      quickPanel?.webContents.send("agent:clipboard", clip.slice(0, 5000));
    }
  });
  if (clip && quickPanel.webContents.getURL()) {
    quickPanel.webContents.send("agent:clipboard", clip.slice(0, 5000));
  }

  quickPanel.show();
  quickPanel.focus();
}

export function closeQuickPanel(): void {
  quickPanel?.hide();
}

/** 速记面板（全局热键唤起的迷你输入窗）。

- 无边框、置顶、宽 640×160（运行中任务时顶部显示状态条）；
- 加载主窗口同一应用，路由 ``/workspace?compose=1``；
- 唤起时可自动预填剪贴板文本（只填入输入框，不自动发送）。
 */
import { BrowserWindow, clipboard, shell } from "electron";
import path from "node:path";

import { supervisor } from "./backend";
import { getMainWindow } from "./window";
import { isLocalOrigin } from "./navigation";

let quickPanel: BrowserWindow | null = null;
/** 已加载的 URL / 令牌（后端重启换端口或换令牌时需要重新加载）。 */
let loadedUrl = "";
let loadedToken = "";

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
      loadedUrl = "";
      loadedToken = "";
    });
    // **D11**：与主窗口同样的导航守卫（此前完全没有 → SPA 里的 target="_blank"
    // 会开出完全不受管的窗口）。
    quickPanel.webContents.setWindowOpenHandler(({ url }) => {
      if (isLocalOrigin(url, supervisor.handle()?.port)) return { action: "deny" };
      try {
        new URL(url);
        void shell.openExternal(url);
      } catch {
        /* 非法 URL 一律拒绝 */
      }
      return { action: "deny" };
    });
    quickPanel.webContents.on("will-navigate", (event, url) => {
      if (!isLocalOrigin(url, supervisor.handle()?.port)) {
        event.preventDefault();
      }
    });
  }

  // **D11**：每次唤起都按**当前** handle 重算 URL —— 此前只在创建时算一次，
  // 后端重启（OS 分配新端口）后速记窗会一直指向死端口。
  const url = `http://127.0.0.1:${handle.port}/workspace?compose=1`;
  if (url !== loadedUrl || handle.token !== loadedToken) {
    loadedUrl = url;
    loadedToken = handle.token;
    void quickPanel
      .loadURL(url, {
        extraHeaders: `X-Agent-Desktop-Token: ${handle.token}`,
      })
      .catch((err: Error) => {
        // 加载失败不应让速记窗变成"点不动的空窗"
        console.error(`[quick] 速记面板加载失败（${url}）：${err.message}`);
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

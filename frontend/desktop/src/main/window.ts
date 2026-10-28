/** 主窗口管理：创建、引导加载、CSP、加载失败重试。 */
import { BrowserWindow, app } from "electron";
import path from "node:path";

import { PATHS } from "../shared/protocol";
import { supervisor } from "./backend";
import { backendState } from "./state";
import { getPaths, resolveSplashPath } from "./paths";
import { getSettings } from "./settings";

let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;
let loadRetries = 0;
const MAX_LOAD_RETRIES = 3;

export function getMainWindow(): BrowserWindow | null {
  return mainWindow;
}

/** 显示启动页（壳内置静态 HTML，不依赖后端）。 */
export function showSplash(): void {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 300,
    frame: false,
    resizable: false,
    show: true,
    backgroundColor: "#0f1115",
    webPreferences: { contextIsolation: true },
  });
  void splashWindow
    .loadFile(resolveSplashPath())
    .catch((err: Error) => {
      // 启动页缺失/加载失败不应中断启动：关掉它并记录原因，主窗口会接手
      console.error(`[window] 启动页加载失败（${resolveSplashPath()}）：${err.message}`);
      splashWindow?.close();
    });
}

export function closeSplash(): void {
  splashWindow?.close();
  splashWindow = null;
}

export function createMainWindow(): void {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    show: false,
    backgroundColor: "#0f1115",
    webPreferences: {
      preload: path.join(__dirname, "..", "..", "dist-preload", "preload", "index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  // 拦截新开窗口与导航到非 loopback 的请求
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const handle = supervisor.handle();
    if (handle && !url.startsWith(`http://127.0.0.1:${handle.port}`)) {
      event.preventDefault();
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  bootstrapIntoWindow();
}

/** 让主窗口经一次性 nonce 引导进入会话。 */
export function bootstrapIntoWindow(): void {
  if (!mainWindow) return;
  const handle = supervisor.handle();
  if (!handle) {
    // 后端未就绪（握手失败 / 超时 / 崩溃）：必须给出可见反馈，
    // 否则就是一个 show:false 的空窗口 —— 用户侧表现为"双击没反应"。
    showErrorPage(new Error("后端服务未就绪，无法进入工作台"));
    return;
  }
  const url = `http://127.0.0.1:${handle.port}${PATHS.bootstrap}?t=${supervisorNonce()}`;
  loadWithRetry(url);
}

/** 后端重启后令牌更换，主窗口需重新引导。 */
export function rebootstrap(): void {
  bootstrapIntoWindow();
}

function supervisorNonce(): string {
  // nonce 由 backend.ts 生成，经这里读取供 bootstrap URL 使用
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (supervisor as any).nonceValue?.() ?? "";
}

function loadWithRetry(url: string): void {
  if (!mainWindow) return;
  void mainWindow
    .loadURL(url)
    .then(() => {
      loadRetries = 0;
      closeSplash();
      // 「启动时最小化到托盘」：窗口建好但不显示，用户从托盘唤起
      if (getSettings().startMinimized) {
        mainWindow?.hide();
      } else {
        mainWindow?.show();
      }
    })
    .catch((err: Error) => {
      loadRetries += 1;
      if (loadRetries <= MAX_LOAD_RETRIES) {
        const delay = 1_000 * loadRetries;
        setTimeout(() => loadWithRetry(url), delay);
      } else {
        showErrorPage(err);
      }
    });
}

function showErrorPage(err: Error): void {
  const status = backendState.status();
  const html = errorPageHtml(err, status.lastError);
  const dataUrl = `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
  closeSplash();
  void mainWindow?.loadURL(dataUrl).catch(() => undefined);
  mainWindow?.show();
}

function errorPageHtml(err: Error, lastError: string | null): string {
  const { logsDir } = getPaths();
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Agent Desktop 启动失败</title>
<style>body{background:#0f1115;color:#e6e6e6;font-family:system-ui;padding:32px;max-width:640px;margin:0 auto}
h1{font-size:20px}code{background:#1c1f26;padding:2px 6px;border-radius:4px}
pre{background:#1c1f26;padding:12px;border-radius:8px;overflow:auto;white-space:pre-wrap}</style></head>
<body><h1>后端服务启动失败</h1>
<p>本地 Agent 服务未能就绪。可尝试：</p>
<ul><li>重启应用</li><li>查看日志目录 <code>${logsDir}</code></li><li>确认端口未被占用</li></ul>
<pre>${escapeHtml(err.message)}${lastError ? "\n\n最近错误：\n" + escapeHtml(lastError) : ""}</pre>
</body></html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

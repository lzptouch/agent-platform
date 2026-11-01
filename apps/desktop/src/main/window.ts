/** 主窗口管理：创建、引导加载、CSP、加载失败重试。 */
import { BrowserWindow, app, shell } from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { PATHS } from "../shared/protocol";
import { supervisor } from "./backend";
import { isLocalOrigin } from "./navigation";
import { backendState } from "./state";
import { getPaths, resolveSplashPath } from "./paths";
import { getSettings } from "./settings";

let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;
let loadRetries = 0;

// 应用是否正在退出：**退出中不能拦截窗口关闭**，否则 app.quit() 永远关不掉窗口。
let quitting = false;
app.on("before-quit", () => {
  quitting = true;
});
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
    // 不能用 loadFile：它内部走 url.format，**不会**对 pathname 做百分号编码，
    // 而 macOS 的安装目录名带空格（productName = "Agent Desktop"），
    // 于是 file:///…/Agent Desktop.app/… 解析失败 → ERR_FAILED (-2) 启动页白屏。
    .loadURL(pathToFileURL(resolveSplashPath()).toString())
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
  // **W8-13 / AUD2-M20**：外部链接改为交给系统浏览器打开（此前一律 deny
  // → 研究结果外链、产物下载、`/docs` 链接在桌面端**全部点不动**；
  // 而 `shell.openExternal` 虽在 IPC 白名单实现却**零调用方**）。
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      const handle = supervisor.handle();
      const local = handle ? `http://127.0.0.1:${handle.port}` : null;
      if (local && parsed.origin === local) {
        return { action: "deny" }; // 本地页面仍走应用内导航
      }
      void shell.openExternal(url); // 外部链接交给系统浏览器
    } catch {
      /* 非法 URL 一律拒绝 */
    }
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const handle = supervisor.handle();
    // **W8-04 / AUD2-H20**：此前用 `url.startsWith("http://127.0.0.1:<port>")`
    // 前缀匹配 → `http://127.0.0.1:8080.evil.com/` **满足该前缀** → 放行到外部站点；
    // 且 `handle` 为 null（握手失败 / 后端崩溃）时守卫**整体失效**，任意导航都被允许。
    // 修复：origin **精确**比较；后端未就绪时**一律拒绝**。
    if (!handle) {
      event.preventDefault();
      return;
    }
    const allowed = `http://127.0.0.1:${handle.port}`;
    try {
      if (new URL(url).origin !== allowed) {
        event.preventDefault();
      }
    } catch {
      event.preventDefault();
    }
  });

  // **D5**：点 × **不销毁**窗口，只隐藏 —— 销毁后托盘「打开主窗口」永远唤不回来。
  mainWindow.on("close", (event) => {
    if (quitting) return; // 应用正在退出 → 放行关闭，否则 app.quit() 关不掉窗口
    event.preventDefault();
    mainWindow?.hide();
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
  // nonce 由 backend.ts 生成，经这里读取供 bootstrap URL 使用。
  // **D15**：此前 `(supervisor as any).nonceValue?.() ?? ""` —— nonceValue() 是**公开方法**，
  // `as any` 掩盖了「取不到 nonce 时静默返回空串 → 引导 401」。
  const nonce = supervisor.nonceValue();
  if (!nonce) {
    throw new Error("后端未就绪：缺少引导 nonce");
  }
  return nonce;
}

/** URL 是否指向本地 sidecar（origin **精确**比较）。 */
function isLocalBackendUrl(url: string): boolean {
  return isLocalOrigin(url, supervisor.handle()?.port);
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

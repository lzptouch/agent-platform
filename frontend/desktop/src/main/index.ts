/** Agent Desktop 主进程入口。

启动顺序（doc/design/03 §2.2）：

1. 单实例锁；
2. 清孤儿进程（上次异常退出残留的 sidecar）；
3. 创建托盘与启动页；
4. spawn 后端 sidecar，等待握手；
5. 引导主窗口进入会话；
6. 注册全局热键、IPC、更新、电源事件。
 */
import { BrowserWindow, app, powerMonitor } from "electron";
import fs from "node:fs";

import { registerIpc } from "./ipc";
import { supervisor } from "./backend";
import { backendState } from "./state";
import { getPaths } from "./paths";
import { createMainWindow, showSplash } from "./window";
import { createTray } from "./tray";
import { registerShortcuts, unregisterShortcuts } from "./shortcuts";
import { setupUpdater } from "./updater";
import { showNotification } from "./notifications";
import { applyAutoLaunch, getSettings } from "./settings";

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const win = getMainWindowSafe();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });

  void main();
}

async function main(): Promise<void> {
  await app.whenReady();
  cleanupOrphans();

  // 壳设置：开机自启（落系统）
  const shellSettings = getSettings();
  applyAutoLaunch(shellSettings.autoLaunch);

  showSplash();
  createTray();
  registerIpc();
  registerShortcuts();
  setupUpdater((info) => {
    showNotification({ title: `新版本 ${info.version} 可用`, body: "重启应用即可完成更新" });
  });

  supervisor.onLog((line) => appendBackendLog(line));

  // 后端状态变化 → 渲染进程（此前 state.onChange 无订阅方，状态变化从不外发）
  backendState.onChange(() => {
    const win = getMainWindowSafe();
    if (!win || win.isDestroyed()) return;
    try {
      win.webContents.send("agent:backend-state", backendState.status());
    } catch {
      // 窗口/渲染帧可能已销毁（启动期切换、退出期），忽略即可
    }
  });

  // 后端事件流 → 渲染进程（此前 agent:backend-event 无发送方，事件链路断开）
  supervisor.onBackendEvent((event) => {
    const win = getMainWindowSafe();
    if (!win || win.isDestroyed()) return;
    try {
      win.webContents.send("agent:backend-event", event);
    } catch {
      // 同上：渲染帧已销毁时忽略
    }
  });

  try {
    await supervisor.start();
    createMainWindow();
  } catch (err) {
    appendBackendLog(`启动失败：${String(err)}`);
    backendState.markCrashed(String(err));
    createMainWindow(); // 让窗口进入错误页（失败原因会显示在页面上）
    showNotification({
      title: "Agent Desktop 启动失败",
      body: String(err).slice(0, 200),
    });
  }

  // 电源事件：挂起期间冻结探活；唤醒后探活 + 补跑错过的定时任务
  powerMonitor.on("suspend", () => backendState.set("degraded"));
  powerMonitor.on("resume", () => void onResume());

  app.on("window-all-closed", () => {
    // 关闭窗口转托盘（不退出）；退出需托盘菜单「退出」或 Cmd+Q
  });
  app.on("before-quit", () => void supervisor.stop());
  app.on("will-quit", () => unregisterShortcuts());
}

function getMainWindowSafe(): BrowserWindow | null {
  const win = BrowserWindow.getAllWindows()[0];
  return win ?? null;
}

async function onResume(): Promise<void> {
  appendBackendLog("系统唤醒，重新探活并补跑错过的定时任务");
  await supervisor.start().catch(() => undefined);
  const handle = supervisor.handle();
  if (!handle) return;
  try {
    await fetch(
      `http://127.0.0.1:${handle.port}/api/v1/desktop/scheduler/resume-scan`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Desktop-Token": handle.token,
        },
        body: JSON.stringify({}),
      },
    );
  } catch {
    // 补跑失败不打断主流程
  }
}

function appendBackendLog(line: string): void {
  try {
    const { logsDir } = getPaths();
    fs.appendFileSync(`${logsDir}\\backend.log`, line);
  } catch {
    // 日志失败不影响主流程
  }
}

/** 上次异常退出残留的 sidecar 进程清理。 */
function cleanupOrphans(): void {
  try {
    const { runStatePath } = getPaths();
    if (!fs.existsSync(runStatePath)) return;
    const state = JSON.parse(fs.readFileSync(runStatePath, "utf-8")) as { pid?: number };
    if (typeof state.pid === "number") {
      try {
        process.kill(state.pid, 0);
        // 进程仍在 → 尝试结束
        if (process.platform === "win32") {
          const { spawnSync } = require("node:child_process");
          spawnSync("taskkill", ["/pid", String(state.pid), "/T", "/F"]);
        } else {
          process.kill(state.pid, "SIGTERM");
        }
      } catch {
        // 进程不存在
      }
    }
    fs.unlinkSync(runStatePath);
  } catch {
    // 清理失败不影响启动
  }
}

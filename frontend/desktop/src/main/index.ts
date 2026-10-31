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
import path from "node:path";

import { registerIpc } from "./ipc";
import { readRunState, reclaimOrphan, supervisor } from "./backend";
import { backendState } from "./state";
import { getPaths } from "./paths";
import { createMainWindow, getMainWindow, showSplash } from "./window";
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

  // 退出清理必须**先武装好**再启动后端：
  // run-state 在握手完成时就会写出，而 start() 还要继续等健康探活；
  // 若把处理器注册放在 start() 之后，落在"已写出 run-state 但尚未启动完成"
  // 这段窗口里的终止信号就会走默认路径 → 侧车残留成孤儿、run-state 残留。
  installExitHandlers();

  // 壳设置：开机自启（落系统）
  const shellSettings = getSettings();
  applyAutoLaunch(shellSettings.autoLaunch);

  showSplash();
  // **D8**：孤儿回收要**确认进程退出**才删 run-state，可能耗时数秒 → 放在启动页之后
  await cleanupOrphans();
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
  app.on("will-quit", () => unregisterShortcuts());
}

/**
 * 安装退出清理（必须在启动后端**之前**武装好）。
 *
 * 两条退出路径都要覆盖：
 *  1. 「托盘退出 / Cmd+Q」→ Electron 的 before-quit；
 *  2. POSIX 的 SIGTERM/SIGINT → 默认行为是**直接终止进程**，before-quit 不触发，
 *     侧车与 run-state 会全部残留（实测：退出后侧车仍在跑，占着端口）。
 */
function installExitHandlers(): void {
  let quitting = false;
  app.on("before-quit", (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    void supervisor.stop().finally(() => {
      // P6-07：应用**正常退出** → 删除 run-state（孤儿已随进程退出，无需下次回收）
      supervisor.clearRunState();
      app.quit();
    });
  });

  for (const sig of ["SIGTERM", "SIGINT"] as NodeJS.Signals[]) {
    process.on(sig, () => {
      if (quitting) return;
      quitting = true;
      void supervisor.stop().finally(() => {
        // P6-07：SIGTERM/SIGINT 属**正常终止信号** → 同样清理 run-state
        supervisor.clearRunState();
        app.exit(0);
      });
    });
  }
}

function getMainWindowSafe(): BrowserWindow | null {
  // **D3**：此前用 `BrowserWindow.getAllWindows()[0]` —— 启动期 [0] 是**启动页**
  // （showSplash() 先于 createMainWindow()），状态/事件全发给启动页 → 渲染进程收不到。
  const win = getMainWindow();
  if (!win || win.isDestroyed()) return null;
  return win;
}

async function onResume(): Promise<void> {
  appendBackendLog("系统唤醒，重新探活并补跑错过的定时任务");
  await supervisor.start().catch(() => undefined);
  const handle = supervisor.handle();
  if (!handle) return;
  // **D9**：休眠时状态被置为 degraded，而 start() 在「child 已存在」时**提前返回**
  // → 永远不会 markReady() → 状态永远停在 degraded → 探活空转、后端假死永不重启。
  backendState.markReady(handle.port, handle.pid);
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
    fs.appendFileSync(path.join(logsDir, "backend.log"), line);
  } catch {
    // 日志失败不影响主流程
  }
}

/**
 * 上次异常退出残留的 sidecar 进程清理（**确认退出后**才删 run-state）。
 *
 * **D8**：此前是「SIGTERM → **立刻** `unlinkSync(run-state)`」→
 * 侧车其实还在跑（文件自己的注释就承认「SIGTERM 后侧车仍在跑」），
 * 凭据却已删除 → 下次启动**再也无法回收** → 直接违反设计文档「不留孤儿」不变式。
 * 且 pid **未做任何归属校验** → PID 复用时会误杀用户机器上的无关进程。
 */
async function cleanupOrphans(): Promise<void> {
  const { runStatePath } = getPaths();
  const record = readRunState(runStatePath);
  if (!record) return;
  const outcome = await reclaimOrphan(record, (line) => appendBackendLog(line));
  appendBackendLog(`孤儿回收：pid=${record.pid} 结果=${outcome}`);
  // "alive"：进程还在（或无法确认归属）→ **保留** run-state，下次启动继续回收
  if (outcome === "alive") return;
  try {
    if (fs.existsSync(runStatePath)) fs.unlinkSync(runStatePath);
  } catch {
    // 清理失败不影响启动
  }
}

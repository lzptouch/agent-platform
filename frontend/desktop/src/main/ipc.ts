/** IPC 白名单（壳 ↔ 渲染进程）。

边界规则（doc/design/03 §8）：

- 所有 IPC 在此登记，preload 不直接触碰 ``ipcRenderer``；
- 每个 handler 第一步做参数校验，失败返回 ``{ok:false, error}`` 而非抛异常；
- 不提供「执行任意命令」「读取任意路径」的通用 IPC。
 */
import { clipboard, dialog, ipcMain, shell, BrowserWindow } from "electron";
import path from "node:path";
import fs from "node:fs";
import http from "node:http";

import type { Result, UpdateInfo } from "../shared/types";
import { PATHS } from "../shared/protocol";
import { supervisor } from "./backend";
import { backendState } from "./state";
import { getPaths } from "./paths";
import { getMainWindow } from "./window";
import { setTrayBadge } from "./tray";
import { showNotification } from "./notifications";
import { checkForUpdates, restartIntoUpdate } from "./updater";
import { setBossKey } from "./shortcuts";
import { closeQuickPanel } from "./quick";
import { applyAutoLaunch, getSettings, updateSettings } from "./settings";

function ok<T extends object>(data: T): Result<T> {
  return { ok: true, ...data };
}
function fail(code: string, message: string): Result<never> {
  return { ok: false, error: { code, message } };
}

export function registerIpc(): void {
  ipcMain.handle("desktop:status", () => ok(backendState.status()));
  ipcMain.handle("desktop:diagnostics", () =>
    ok({ text: JSON.stringify(backendState.status(), null, 2) }),
  );

  ipcMain.handle("desktop:chooseDirectory", async (_e, opts?: { title?: string }) => {
    const win = BrowserWindow.getFocusedWindow() ?? getMainWindow();
    if (!win) return fail("E_NO_WINDOW", "无可用窗口");
    const result = await dialog.showOpenDialog(win, {
      title: opts?.title ?? "选择目录",
      properties: ["openDirectory", "createDirectory"],
    });
    return ok({ path: result.canceled ? null : result.filePaths[0] });
  });

  ipcMain.handle(
    "desktop:saveArtifact",
    async (_e, req: { url?: string; suggestedName?: string }) => {
      const url = req?.url;
      if (typeof url !== "string" || !url) return fail("E_INVALID", "缺少 url");
      const win = getMainWindow();
      if (!win) return fail("E_NO_WINDOW", "无可用窗口");
      const result = await dialog.showSaveDialog(win, {
        defaultPath: req.suggestedName ?? path.basename(url) ?? "artifact",
      });
      if (result.canceled || !result.filePath) return ok({ path: null });
      try {
        await downloadToFile(url, result.filePath);
        return ok({ path: result.filePath });
      } catch (err) {
        return fail("E_IO", `保存失败: ${String(err)}`);
      }
    },
  );

  ipcMain.handle("desktop:revealPath", (_e, p: unknown) => {
    if (typeof p !== "string" || !p) return fail("E_INVALID", "缺少路径");
    shell.showItemInFolder(p);
    return ok({ ok: true });
  });

  ipcMain.handle("desktop:openExternal", (_e, url: unknown) => {
    if (typeof url !== "string" || !/^https?:\/\//.test(url)) {
      return fail("E_INVALID", "仅允许 http/https");
    }
    void shell.openExternal(url);
    return ok({ ok: true });
  });

  ipcMain.handle(
    "desktop:notify",
    (_e, req: { title?: string; body?: string; runId?: string }) => {
      if (typeof req?.title !== "string" || !req.title) {
        return fail("E_INVALID", "缺少标题");
      }
      const shown = showNotification({
        title: req.title,
        body: req.body,
        runId: req.runId,
      });
      return shown ? ok({ ok: true }) : fail("E_NOTIFY_UNAVAILABLE", "系统通知不可用");
    },
  );

  ipcMain.handle("desktop:setTrayBadge", (_e, text: unknown) => {
    setTrayBadge(typeof text === "string" ? text : null);
    return ok({ ok: true });
  });

  ipcMain.handle("desktop:checkForUpdates", () => ok({ info: checkForUpdates() }));
  ipcMain.handle("desktop:restartIntoUpdate", () => {
    restartIntoUpdate();
    return ok({});
  });

  ipcMain.handle("desktop:readClipboard", () => ok({ text: clipboard.readText() }));
  ipcMain.handle("desktop:setClipboard", (_e, text: unknown) => {
    if (typeof text !== "string") return fail("E_INVALID", "仅支持文本");
    clipboard.writeText(text);
    return ok({ ok: true });
  });

  ipcMain.handle("desktop:minimizeToTray", () => {
    getMainWindow()?.hide();
    return ok({});
  });
  ipcMain.handle("desktop:quit", () => {
    void appQuit();
    return ok({});
  });

  // ---- 壳设置（Boss Key / 开机自启 / 启动最小化）----
  ipcMain.handle("desktop:getSettings", () => ok({ settings: getSettings() }));

  ipcMain.handle("desktop:setBossKey", (_e, accelerator: unknown) => {
    if (accelerator !== null && typeof accelerator !== "string") {
      return fail("E_INVALID", "仅支持字符串或 null");
    }
    const res = setBossKey(accelerator === null ? null : String(accelerator));
    if (!res.registered) {
      return fail("E_SHORTCUT_CONFLICT", `快捷键被占用: ${res.conflicts.join(", ")}`);
    }
    return ok({ settings: getSettings() });
  });

  ipcMain.handle("desktop:setAutoLaunch", (_e, enabled: unknown) => {
    if (typeof enabled !== "boolean") return fail("E_INVALID", "仅支持布尔值");
    const settings = updateSettings({ autoLaunch: enabled });
    applyAutoLaunch(enabled);
    return ok({ settings });
  });

  ipcMain.handle("desktop:setStartMinimized", (_e, enabled: unknown) => {
    if (typeof enabled !== "boolean") return fail("E_INVALID", "仅支持布尔值");
    const settings = updateSettings({ startMinimized: enabled });
    return ok({ settings });
  });

  // ---- 速记窗提交后：关小窗 + 通知主窗口跳到该 run ----
  ipcMain.handle("desktop:openRun", (_e, runId: unknown) => {
    if (typeof runId !== "string" || !runId) return fail("E_INVALID", "缺少 runId");
    closeQuickPanel();
    const win = getMainWindow();
    if (win) {
      win.show();
      win.focus();
      win.webContents.send("agent:open-run", runId);
    }
    return ok({});
  });
}

function downloadToFile(url: string, dest: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const handle = supervisor.handle();
    if (!handle) return reject(new Error("后端未就绪"));
    const target = new URL(url, `http://127.0.0.1:${handle.port}`);
    const file = fs.createWriteStream(dest);
    const req = http.get(target, { headers: { "X-Agent-Desktop-Token": handle.token } }, (res) => {
      if (res.statusCode !== 200) {
        file.close();
        fs.unlink(dest, () => undefined);
        reject(new Error(`HTTP ${res.statusCode}`));
        return;
      }
      res.pipe(file);
      file.on("finish", () => file.close(() => resolve()));
    });
    req.on("error", (err) => {
      file.close();
      fs.unlink(dest, () => undefined);
      reject(err);
    });
  });
}

async function appQuit(): Promise<void> {
  const { app } = await import("electron");
  app.quit();
}

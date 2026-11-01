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
    // **D13**：包 try/catch —— quitAndInstall 未初始化时会同步抛异常，
    // 直接冒泡到 IPC → 渲染进程侧 unhandled rejection。
    try {
      const res = restartIntoUpdate();
      if (!res.ok) return res;
      return ok({});
    } catch (err) {
      return fail("E_UPDATER_FAILED", `重启更新失败: ${String(err)}`);
    }
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
    // **W7-02 / AUD2-C02（令牌外泄）**：`new URL(url, base)` 在 `url` 是**绝对地址**时
    // 会**忽略 base** → 请求会带着常驻的 `X-Agent-Desktop-Token` 发往**外部主机**。
    // 该令牌可直接通过后端 `request_authorized()` → 等于把整个 `/api/v1/**` 的权限外送。
    // 修复：origin 必须**精确**等于本地 sidecar 的 origin。
    const allowedOrigin = `http://127.0.0.1:${handle.port}`;
    if (target.origin !== allowedOrigin) {
      return reject(new Error(`目标 origin 不被允许: ${target.origin}`));
    }
    const file = fs.createWriteStream(dest);
    // **W8-05 / AUD2-H22**：WriteStream 无 "error" 监听 → 磁盘满 / 目标无权限 /
    // 用户选了已删除的目录时，Node 对无监听器的 "error" 事件**抛未捕获异常**
    // → **Electron 主进程崩溃、所有窗口消失**。
    file.on("error", (err) => {
      file.close();
      fs.unlink(dest, () => undefined);
      reject(err);
    });
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

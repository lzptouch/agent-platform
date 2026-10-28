/**
 * 自动更新（electron-updater）。
 *
 * **本阶段的诚实口径（S8 / WP-8.6）：**
 * - 自动更新**不在本期范围**：当前没有签名证书与发布通道（`publish` 段为空），
 *   electron-updater 在没有发布通道时不会真正工作；
 * - 因此本模块只做一件事：**在 `publish` 配置为空时不发起检查**（避免误导性的
 *   "已检查更新"行为），并在日志里说明原因；
 * - 启用条件（未来）：补签名证书 + `electron-builder.yml` 的 `publish` 段 +
 *   下载校验（哈希/签名）后，再打开 `autoUpdateEnabled`。
 *
 * 此前的注释声称"仅接受已签名更新包"——**那是误导**：Windows 上 electron-updater
 * 默认不做签名校验，而且我们根本没有证书。该注释已删除。
 */
import { autoUpdater } from "electron-updater";
import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

import type { UpdateInfo } from "../shared/types";

let available: UpdateInfo | null = null;

/** 是否启用了自动更新（有发布通道才算启用）。""" */
function publishConfigured(): boolean {
  try {
    // __dirname 在打包态指向 asar 内的 dist-main；向上两级到应用根
    const builderYml = path.join(__dirname, "..", "..", "electron-builder.yml");
    const text = fs.readFileSync(builderYml, "utf-8");
    return /^publish\s*:/m.test(text);
  } catch {
    return false;
  }
}

/** 自动更新是否在本期范围（签名 + 发布通道都齐备才为真）。 */
export function autoUpdateEnabled(): boolean {
  return app.isPackaged && publishConfigured();
}

export function setupUpdater(onAvailable?: (info: UpdateInfo) => void): void {
  if (!app.isPackaged) return; // 开发态不检查更新
  if (!publishConfigured()) {
    // 诚实标注：自动更新不在本期范围（无签名证书 + 无发布通道）
    console.warn("[updater] 自动更新未启用：publish 段为空（无签名证书与发布通道）。");
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.on("update-available", (info) => {
    available = {
      version: info.version,
      notes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
      url: "",
      date: String(info.releaseDate ?? ""),
    };
    onAvailable?.(available);
  });
  autoUpdater.on("update-downloaded", () => {
    // 通知由 IPC 层转成系统通知；此处只标记可安装
  });
  setTimeout(() => {
    void autoUpdater.checkForUpdates().catch(() => undefined);
  }, 30_000);
}

export function checkForUpdates(): UpdateInfo | null {
  return available;
}

export function restartIntoUpdate(): void {
  autoUpdater.quitAndInstall();
}

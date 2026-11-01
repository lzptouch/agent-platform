/** Preload：白名单桥。

渲染进程拿到的是一个**固定对象** ``window.agentDesktop``，而不是回调或原始
``ipcRenderer``。所有方法先经主进程参数校验。
 */
import { contextBridge, ipcRenderer } from "electron";

import type {
  BackendEvent,
  BackendStatus,
  DirectoryResult,
  Result,
  SaveResult,
  ShellSettings,
  UpdateInfo,
} from "../shared/types";

const api = {
  // 运行态
  status: (): Promise<Result<BackendStatus>> => ipcRenderer.invoke("desktop:status"),
  diagnostics: (): Promise<Result<{ text: string }>> => ipcRenderer.invoke("desktop:diagnostics"),

  // 文件 / 目录
  chooseDirectory: (opts?: { title?: string }): Promise<Result<DirectoryResult>> =>
    ipcRenderer.invoke("desktop:chooseDirectory", opts),
  saveArtifact: (req: { url: string; suggestedName?: string }): Promise<Result<SaveResult>> =>
    ipcRenderer.invoke("desktop:saveArtifact", req),
  revealPath: (path: string): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:revealPath", path),
  openExternal: (url: string): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:openExternal", url),

  // 通知与角标
  notify: (req: { title: string; body?: string; runId?: string }): Promise<Result<{ ok: boolean }>> =>
    ipcRenderer.invoke("desktop:notify", req),
  setTrayBadge: (text: string | null): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:setTrayBadge", text),

  // 更新
  checkForUpdates: (): Promise<Result<{ info: UpdateInfo | null }>> =>
    ipcRenderer.invoke("desktop:checkForUpdates"),
  restartIntoUpdate: (): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:restartIntoUpdate"),

  // 剪贴板
  readClipboard: (): Promise<Result<{ text: string }>> =>
    ipcRenderer.invoke("desktop:readClipboard"),
  setClipboard: (text: string): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:setClipboard", text),

  // 窗口控制
  minimizeToTray: (): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:minimizeToTray"),
  quit: (): Promise<Result<Record<string, never>>> => ipcRenderer.invoke("desktop:quit"),

  // 壳设置（Boss Key / 开机自启 / 启动最小化）
  getSettings: (): Promise<Result<{ settings: ShellSettings }>> =>
    ipcRenderer.invoke("desktop:getSettings"),
  setBossKey: (accelerator: string | null): Promise<Result<{ settings: ShellSettings }>> =>
    ipcRenderer.invoke("desktop:setBossKey", accelerator),
  setAutoLaunch: (enabled: boolean): Promise<Result<{ settings: ShellSettings }>> =>
    ipcRenderer.invoke("desktop:setAutoLaunch", enabled),
  setStartMinimized: (enabled: boolean): Promise<Result<{ settings: ShellSettings }>> =>
    ipcRenderer.invoke("desktop:setStartMinimized", enabled),

  // 速记窗提交后：关小窗并让主窗口跳到该 run
  openRun: (runId: string): Promise<Result<Record<string, never>>> =>
    ipcRenderer.invoke("desktop:openRun", runId),

  // 事件订阅（后端 → 壳 → 渲染进程；返回取消订阅函数）
  onBackendEvent: (cb: (event: BackendEvent) => void): (() => void) => {
    const handler = (_e: unknown, payload: BackendEvent) => cb(payload);
    ipcRenderer.on("agent:backend-event", handler);
    return () => ipcRenderer.removeListener("agent:backend-event", handler);
  },
  onBackendState: (cb: (status: BackendStatus) => void): (() => void) => {
    const handler = (_e: unknown, payload: BackendStatus) => cb(payload);
    ipcRenderer.on("agent:backend-state", handler);
    return () => ipcRenderer.removeListener("agent:backend-state", handler);
  },
  onClipboard: (cb: (text: string) => void): (() => void) => {
    const handler = (_e: unknown, text: string) => cb(text);
    ipcRenderer.on("agent:clipboard", handler);
    return () => ipcRenderer.removeListener("agent:clipboard", handler);
  },
  onOpenRun: (cb: (runId: string) => void): (() => void) => {
    const handler = (_e: unknown, runId: string) => cb(runId);
    ipcRenderer.on("agent:open-run", handler);
    return () => ipcRenderer.removeListener("agent:open-run", handler);
  },
};

contextBridge.exposeInMainWorld("agentDesktop", api);

export type AgentDesktopApi = typeof api;

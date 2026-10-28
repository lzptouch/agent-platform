/** 壳 ↔ 渲染进程 的共享类型（IPC 契约）。

契约细节见 doc/design/05-数据模型与API设计.md §4。
 */

export type Result<T> = { ok: true } & T | { ok: false; error: { code: string; message: string } };

export interface DirectoryResult {
  path: string | null;
}

export interface SaveResult {
  path: string | null;
}

export interface OperationResult {
  ok: boolean;
}

export interface UpdateInfo {
  version: string;
  notes: string;
  url: string;
  date: string;
}

export interface BackendStatus {
  state: BackendState;
  port: number | null;
  pid: number | null;
  restarts: number;
  lastError: string | null;
}

/** 后端状态机（doc/design/03 §3.4） */
export type BackendState =
  | "idle"
  | "starting"
  | "ready"
  | "degraded"
  | "crashed"
  | "stopping"
  | "stopped";

export interface InstallProgress {
  component: string;
  percent: number;
  status: "downloading" | "installing" | "done" | "error";
  message?: string;
}

export interface InstallProgressHandle {
  handle: string;
}

export interface BackendEvent {
  /** 事件类型：后端可自由扩展（backend:state / workspace_changed / run_started / scheduler_rescued …） */
  type: string;
  id?: number;
  ts?: string;
  [key: string]: unknown;
}

/** 壳设置（批次 02：Boss Key / 开机自启 / 启动最小化）。 */
export interface ShellSettings {
  /** Boss Key 快捷键（Electron accelerator）；null = 未绑定（默认不绑定） */
  bossKey: string | null;
  /** 开机自启 */
  autoLaunch: boolean;
  /** 启动时最小化到托盘 */
  startMinimized: boolean;
}

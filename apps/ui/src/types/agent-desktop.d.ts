/** window.agentDesktop 的全局类型声明（桌面端 preload 注入）。

该对象仅在桌面端存在；Web 形态下为 ``undefined``，前端须先判存在再使用。
 */

export interface AgentDesktopResult<T> {
  ok: boolean
  error?: { code: string; message: string }
}

export type AgentDesktopData<T> = ({ ok: true } & T) | { ok: false; error: { code: string; message: string } }

/** 壳设置（批次 02）：Boss Key / 开机自启 / 启动最小化。 */
export interface ShellSettings {
  /** Boss Key 快捷键；null = 未绑定（默认不绑定） */
  bossKey: string | null
  /** 开机自启 */
  autoLaunch: boolean
  /** 启动时最小化到托盘 */
  startMinimized: boolean
}

/** 后端状态机（与 `apps/desktop/src/shared/types.ts` 对齐） */
export type BackendState =
  | 'idle'
  | 'starting'
  | 'ready'
  | 'degraded'
  | 'crashed'
  | 'stopping'
  | 'stopped'

/** 后端状态快照（P4-14：渲染侧据此展示**降级态**） */
export interface BackendStatus {
  state: BackendState
  port: number | null
  pid: number | null
  restarts: number
  lastError: string | null
}

export interface AgentDesktopApi {
  status(): Promise<AgentDesktopData<unknown>>
  diagnostics(): Promise<AgentDesktopData<{ text: string }>>

  chooseDirectory(opts?: { title?: string }): Promise<AgentDesktopData<{ path: string | null }>>
  saveArtifact(req: { url: string; suggestedName?: string }): Promise<AgentDesktopData<{ path: string | null }>>
  /** P4-14：订阅后端状态变化（渲染侧据此展示降级态） */
  onBackendState(cb: (status: BackendStatus) => void): (() => void)
  revealPath(path: string): Promise<AgentDesktopData<Record<string, never>>>
  openExternal(url: string): Promise<AgentDesktopData<Record<string, never>>>

  notify(req: { title: string; body?: string; runId?: string }): Promise<AgentDesktopData<{ ok: boolean }>>
  setTrayBadge(text: string | null): Promise<AgentDesktopData<Record<string, never>>>

  checkForUpdates(): Promise<AgentDesktopData<{ info: unknown | null }>>
  restartIntoUpdate(): Promise<AgentDesktopData<Record<string, never>>>

  readClipboard(): Promise<AgentDesktopData<{ text: string }>>
  setClipboard(text: string): Promise<AgentDesktopData<Record<string, never>>>

  minimizeToTray(): Promise<AgentDesktopData<Record<string, never>>>
  quit(): Promise<AgentDesktopData<Record<string, never>>>

  // 壳设置（批次 02）
  getSettings(): Promise<AgentDesktopData<{ settings: ShellSettings }>>
  setBossKey(accelerator: string | null): Promise<AgentDesktopData<{ settings: ShellSettings }>>
  setAutoLaunch(enabled: boolean): Promise<AgentDesktopData<{ settings: ShellSettings }>>
  setStartMinimized(enabled: boolean): Promise<AgentDesktopData<{ settings: ShellSettings }>>
  /** 速记窗提交后：关小窗并让主窗口跳到该 run */
  openRun(runId: string): Promise<AgentDesktopData<Record<string, never>>>

  onBackendEvent(cb: (event: unknown) => void): () => void
  onClipboard(cb: (text: string) => void): () => void
  onOpenRun(cb: (runId: string) => void): () => void
}

declare global {
  interface Window {
    agentDesktop?: AgentDesktopApi
  }
}

export {}

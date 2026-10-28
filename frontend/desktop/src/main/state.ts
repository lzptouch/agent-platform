/** 后端进程状态机。

状态流转见 doc/design/03 §3.1。这里只做「记录当前状态 + 广播」，
不含恢复逻辑（恢复逻辑在 backend.ts）。
 */
import type { BackendState, BackendStatus } from "../shared/types";

type Listener = (state: BackendState) => void;

class BackendStateMachine {
  private state: BackendState = "idle";
  private listeners = new Set<Listener>();
  private restarts = 0;
  private lastError: string | null = null;
  private port: number | null = null;
  private pid: number | null = null;

  current(): BackendState {
    return this.state;
  }

  set(next: BackendState): void {
    if (next === this.state) return;
    this.state = next;
    for (const fn of this.listeners) fn(next);
  }

  onChange(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  markReady(port: number, pid: number): void {
    this.port = port;
    this.pid = pid;
    this.restarts = 0;
    this.lastError = null;
    this.set("ready");
  }

  markCrashed(error: string | null): void {
    this.lastError = error;
    this.restarts += 1;
    this.set("crashed");
  }

  noteRestart(): void {
    this.restarts += 1;
  }

  status(): BackendStatus {
    return {
      state: this.state,
      port: this.port,
      pid: this.pid,
      restarts: this.restarts,
      lastError: this.lastError,
    };
  }
}

export const backendState = new BackendStateMachine();

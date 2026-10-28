/** 后端 sidecar 进程编排：spawn / 握手 / 探活 / 重启 / 优雅退出。

设计见 doc/design/03-桌面壳与后端进程编排设计.md。
 */
import { spawn, type ChildProcess } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import { app } from "electron";

import type { BackendEvent } from "../shared/types";
import {
  ENV,
  HANDSHAKE_PREFIX,
  HANDSHAKE_TIMEOUT_MS,
  HEALTH_FAIL_THRESHOLD,
  HEALTH_INTERVAL_MS,
  PATHS,
  RESTART_BACKOFF_MS,
  RESTART_BREAKER_THRESHOLD,
  type HandshakePayload,
} from "../shared/protocol";
import { backendState } from "./state";
import { getPaths, resolveBackendDir, resolveFrontendDist, resolvePython } from "./paths";
import { startEventStream } from "./backend-events";

export interface BackendHandle {
  port: number;
  pid: number;
  token: string;
}

class BackendSupervisor {
  private child: ChildProcess | null = null;
  private token = "";
  private nonce = "";
  private handshake: HandshakePayload | null = null;
  private healthTimer: NodeJS.Timeout | null = null;
  private healthFails = 0;
  private restarting = false;
  private listeners = new Set<(line: string) => void>();
  private eventListeners = new Set<(event: BackendEvent) => void>();
  private stopEventStream: (() => void) | null = null;

  tokenValue(): string {
    return this.token;
  }

  nonceValue(): string {
    return this.nonce;
  }

  payload(): HandshakePayload | null {
    return this.handshake;
  }

  handle(): BackendHandle | null {
    if (!this.handshake) return null;
    return { port: this.handshake.port, pid: this.handshake.pid, token: this.token };
  }

  onLog(fn: (line: string) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** 订阅后端事件流（后端 → 壳 → 渲染进程）。 */
  onBackendEvent(fn: (event: BackendEvent) => void): () => void {
    this.eventListeners.add(fn);
    return () => this.eventListeners.delete(fn);
  }

  private emitBackendEvent(event: BackendEvent): void {
    for (const fn of this.eventListeners) fn(event);
  }

  private emitLog(line: string): void {
    for (const fn of this.listeners) fn(line);
  }

  // ------------------------------------------------------------------ //
  // 启动
  // ------------------------------------------------------------------ //
  async start(): Promise<BackendHandle> {
    if (this.child) {
      const existing = this.handle();
      if (existing) return existing;
    }
    backendState.set("starting");

    this.token = crypto.randomBytes(32).toString("hex");
    this.nonce = crypto.randomBytes(32).toString("hex");

    const paths = getPaths();
    const python = resolvePython();
    const backendDir = resolveBackendDir();

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      [ENV.desktop]: "1",
      [ENV.token]: this.token,
      [ENV.bootstrapNonce]: this.nonce,
      [ENV.protocol]: "1",
      [ENV.dataDir]: paths.dataDir,
      [ENV.frontendDist]: resolveFrontendDist(),
      [ENV.playwrightBrowsersPath]: `${paths.dataDir}\\browsers`,
    };

    this.child = spawn(python, ["-m", "app.desktop.launcher"], {
      cwd: backendDir,
      env,
      windowsHide: true,
    });

    this.child.stderr?.on("data", (chunk: Buffer) => {
      this.emitLog(chunk.toString("utf-8"));
    });

    const handshake = await this.waitForHandshake(this.child);
    this.handshake = handshake;
    backendState.markReady(handshake.port, handshake.pid);
    this.writeRunState(handshake.port, handshake.pid);
    this.startEventStream(handshake.port);

    this.child.on("exit", (code, signal) => this.onExit(code, signal));

    await this.waitForHealthy(handshake.port);
    this.startHealthLoop();
    return this.handle()!;
  }

  // ------------------------------------------------------------------ //
  // 握手
  // ------------------------------------------------------------------ //
  private waitForHandshake(child: ChildProcess): Promise<HandshakePayload> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error(`后端 ${HANDSHAKE_TIMEOUT_MS / 1000}s 内未完成握手`));
      }, HANDSHAKE_TIMEOUT_MS);

      const onData = (chunk: Buffer) => {
        const text = chunk.toString("utf-8");
        const idx = text.indexOf(HANDSHAKE_PREFIX);
        if (idx === -1) {
          this.emitLog(text);
          return;
        }
        const line = text.slice(idx + HANDSHAKE_PREFIX.length).split(/\r?\n/)[0];
        try {
          const payload = JSON.parse(line) as HandshakePayload;
          cleanup();
          resolve(payload);
        } catch {
          this.emitLog(text);
        }
      };
      const onErr = (err: Error) => {
        cleanup();
        reject(err);
      };
      const cleanup = () => {
        clearTimeout(timer);
        child.stdout?.off("data", onData);
        child.off("error", onErr);
      };
      child.stdout?.on("data", onData);
      child.on("error", onErr);
    });
  }

  // ------------------------------------------------------------------ //
  // 健康探活
  // ------------------------------------------------------------------ //
  private startHealthLoop(): void {
    this.stopHealthLoop();
    this.healthFails = 0;
    this.healthTimer = setInterval(() => void this.checkHealth(), HEALTH_INTERVAL_MS);
  }

  private stopHealthLoop(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  private async checkHealth(): Promise<void> {
    if (!this.handshake || backendState.current() !== "ready") return;
    const ok = await this.ping(this.handshake.port, this.token);
    if (ok) {
      this.healthFails = 0;
      return;
    }
    this.healthFails += 1;
    if (this.healthFails >= HEALTH_FAIL_THRESHOLD) {
      this.emitLog("健康探活连续失败，判定后端挂死");
      await this.restart("health-fail");
    }
  }

  private async waitForHealthy(port: number): Promise<void> {
    const delays = [1_000, 2_000, 4_000];
    for (let i = 0; i < delays.length; i += 1) {
      if (await this.ping(port, this.token)) return;
      await sleep(delays[i]);
    }
    backendState.set("degraded");
  }

  private ping(port: number, token: string): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(
        {
          host: "127.0.0.1",
          port,
          path: PATHS.ping,
          headers: { "X-Agent-Desktop-Token": token },
          timeout: 3_000,
        },
        (res) => {
          res.resume();
          resolve(res.statusCode === 200);
        },
      );
      req.on("timeout", () => {
        req.destroy();
        resolve(false);
      });
      req.on("error", () => resolve(false));
    });
  }

  // ------------------------------------------------------------------ //
  // 崩溃与重启
  // ------------------------------------------------------------------ //
  private onExit(code: number | null, signal: string | null): void {
    this.emitLog(`后端退出：code=${code} signal=${signal}`);
    this.stopHealthLoop();
    this.child = null;
    this.handshake = null;
    if (backendState.current() === "stopping" || backendState.current() === "stopped") return;
    backendState.markCrashed(code !== 0 ? `exit code ${code}` : null);
    void this.restart("exit");
  }

  async restart(reason: string): Promise<void> {
    if (this.restarting) return;
    this.restarting = true;
    try {
      this.emitLog(`后端重启（原因：${reason}）`);
      if (backendState.status().restarts >= RESTART_BREAKER_THRESHOLD) {
        backendState.set("degraded");
        this.emitLog("连续重启失败，已熔断；请查看日志");
        return;
      }
      backendState.noteRestart();
      const backoff = RESTART_BACKOFF_MS[
        Math.min(backendState.status().restarts - 1, RESTART_BACKOFF_MS.length - 1)
      ];
      await sleep(backoff);
      this.killTree();
      await this.start();
      // 重启后令牌更换，主窗口需重新引导
      const { rebootstrap } = await import("./window");
      rebootstrap();
    } catch (err) {
      this.emitLog(`重启失败：${String(err)}`);
    } finally {
      this.restarting = false;
    }
  }

  // ------------------------------------------------------------------ //
  // 优雅退出
  // ------------------------------------------------------------------ //
  async stop(): Promise<void> {
    backendState.set("stopping");
    this.stopHealthLoop();
    this.stopEventStream?.();
    this.stopEventStream = null;
    const handle = this.handle();
    if (handle) {
      await new Promise<void>((resolve) => {
        const req = http.request(
          {
            host: "127.0.0.1",
            port: handle.port,
            path: PATHS.shutdown,
            method: "POST",
            headers: { "X-Agent-Desktop-Token": handle.token },
            timeout: 2_000,
          },
          () => resolve(),
        );
        req.on("error", () => resolve());
        req.end();
      });
      await sleep(800);
    }
    this.killTree();
    this.clearRunState();
    backendState.set("stopped");
  }

  // ------------------------------------------------------------------ //
  // 运行态记录（孤儿回收依据）
  // ------------------------------------------------------------------ //
  private writeRunState(port: number, pid: number): void {
    try {
      const { runStatePath } = getPaths();
      fs.writeFileSync(
        runStatePath,
        JSON.stringify({ pid, port, started_at: new Date().toISOString() }, null, 2),
        "utf-8",
      );
    } catch {
      // 记录失败不影响启动（下次启动无法回收孤儿，但不影响本次运行）
    }
  }

  private clearRunState(): void {
    try {
      const { runStatePath } = getPaths();
      if (fs.existsSync(runStatePath)) fs.unlinkSync(runStatePath);
    } catch {
      // 清理失败不影响退出
    }
  }

  private startEventStream(port: number): void {
    this.stopEventStream?.();
    this.stopEventStream = startEventStream({
      port,
      token: this.token,
      onEvent: (event) => this.emitBackendEvent(event),
      onError: () => undefined,
    });
  }

  /** Windows 下用 taskkill /T 清进程树；POSIX 下进程组退出。 */
  private killTree(): void {
    const child = this.child;
    if (!child || child.pid == null) return;
    const pid = child.pid;
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGTERM");
      }
    } catch {
      // 进程可能已退出
    }
    this.child = null;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const supervisor = new BackendSupervisor();

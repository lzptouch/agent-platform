/** 后端 sidecar 进程编排：spawn / 握手 / 探活 / 重启 / 优雅退出。

设计见 doc/design/03-桌面壳与后端进程编排设计.md。
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { app } from "electron";

/**
 * `utilityProcess` 的最小类型声明。
 *
 * Electron 的类型定义把 `utilityProcess` 放在 `Electron.CrossProcessExports`
 * 命名空间下，而本工程用 `moduleResolution: node`（node10）**无法解析**
 * `electron/main` 子路径 → 运行时从主模块取，类型用局部声明。
 */
interface UtilityProcessModule {
  fork(
    modulePath: string,
    args?: string[],
    options?: Record<string, unknown>,
  ): Electron.UtilityProcess;
}

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { utilityProcess } = require("electron") as { utilityProcess: UtilityProcessModule };

import type { BackendEvent } from "../shared/types";
import {
  ENV,
  ENV_MISSED_WINDOW_HOURS,
  HANDSHAKE_PREFIX,
  HANDSHAKE_TIMEOUT_MS,
  HEALTH_FAIL_THRESHOLD,
  HEALTH_INTERVAL_MS,
  HEALTHY_RESET_MS,
  MISSED_WINDOW_HOURS,
  PATHS,
  RESTART_BACKOFF_MS,
  RESTART_BREAKER_THRESHOLD,
  type HandshakePayload,
} from "../shared/protocol";
import { backendState } from "./state";
import {
  getPaths,
  resolveBackendDir,
  resolveFrontendDist,
  resolveServerEntry,
} from "./paths";
import { startEventStream } from "./backend-events";

export interface BackendHandle {
  port: number;
  pid: number;
  token: string;
}

/** 运行态记录（run-state.json）：孤儿回收的依据。 */
export interface RunStateRecord {
  pid: number;
  port?: number;
  started_at?: string;
  /** 拉起 sidecar 的解释器路径（归属校验用）。 */
  exe?: string;
}

/** 孤儿回收结果。 */
export type ReclaimOutcome = "gone" | "killed" | "not-ours" | "alive";

class BackendSupervisor {
  private child: Electron.UtilityProcess | null = null;
  /** sidecar 是否已退出（UtilityProcess 无 exitCode / signalCode）。 */
  private childExited = false;
  private token = "";
  private nonce = "";
  private handshake: HandshakePayload | null = null;
  private healthTimer: NodeJS.Timeout | null = null;
  private healthFails = 0;
  private restarting = false;
  private listeners = new Set<(line: string) => void>();
  private eventListeners = new Set<(event: BackendEvent) => void>();
  private stopEventStream: (() => void) | null = null;
  /** 启动中的 Promise：**幂等**的关键（见 start()）。 */
  private startPromise: Promise<BackendHandle> | null = null;
  /** 连续健康起点（毫秒时间戳）：满 HEALTHY_RESET_MS 才复位熔断计数。 */
  private healthySince = 0;
  /** 重启重试定时器（退出时要清掉）。 */
  private retryTimer: NodeJS.Timeout | null = null;

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
  /**
   * 启动后端（**幂等**）。
   *
   * **D1**：此前 `if (this.child) { const existing = this.handle(); if (existing) return existing; }`
   * —— 握手**尚未完成**时 handle() 为 null → 继续往下走 → 生成**新令牌**并 spawn
   * **第二个** sidecar，第一个变成孤儿（且它仍持旧令牌）→ 健康探活/SSE 全部 401
   * → 无限重启。修复：启动过程用**同一个 in-flight Promise** 收敛，重复调用直接复用。
   */
  async start(): Promise<BackendHandle> {
    if (this.startPromise) return this.startPromise;
    const existing = this.handle();
    if (existing) return existing;
    const promise = this.spawnAndHandshake();
    this.startPromise = promise;
    try {
      return await promise;
    } finally {
      this.startPromise = null;
    }
  }

  private async spawnAndHandshake(): Promise<BackendHandle> {
    backendState.set("starting");

    this.token = crypto.randomBytes(32).toString("hex");
    this.nonce = crypto.randomBytes(32).toString("hex");

    const paths = getPaths();
    const entry = resolveServerEntry();
    const backendDir = resolveBackendDir();

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      [ENV.desktop]: "1",
      [ENV.token]: this.token,
      [ENV.bootstrapNonce]: this.nonce,
      [ENV.protocol]: "1",
      [ENV.dataDir]: paths.dataDir,
      [ENV.frontendDist]: resolveFrontendDist(),
      [ENV.serverEntry]: entry,
      [ENV.playwrightBrowsersPath]: path.join(paths.dataDir, "browsers"),
      // **D15**：此前**从未注入** → 后端 desktop_missed_window_hours 永远取默认 6
      [ENV_MISSED_WINDOW_HOURS]: String(MISSED_WINDOW_HOURS),
    };

    // **utilityProcess**：Electron 官方 Node 子进程（崩溃隔离 + 可加载原生模块）。
    // 与 `spawn` 的差异：stdout/stderr 是**流**（`.on("data")`），
    // 退出事件只给 code（无 signal），`kill()` 直接结束。
    this.childExited = false;
    this.child = utilityProcess.fork(entry, [], {
      cwd: backendDir,
      env,
      serviceName: "agent-server",
      stdio: "pipe",
    });

    const child = this.child;
    child.stderr?.on("data", (chunk: Buffer) => {
      this.emitLog(chunk.toString("utf-8"));
    });

    try {
      const handshake = await this.waitForHandshake(child);
      this.handshake = handshake;
      backendState.markReady(handshake.port, handshake.pid);
      this.healthySince = Date.now();
      this.writeRunState(handshake.port, handshake.pid, entry);
      this.startEventStream(handshake.port);

      child.on("exit", (code: number) => this.onExit(code, null));
      // 握手完成 → 挂上 exit 监听之间进程已退出（极窄竞态）：视为启动失败
      if (this.childExited) {
        throw new Error("后端在握手完成后立即退出");
      }

      await this.waitForHealthy(handshake.port);
      this.startHealthLoop();
      return this.handle()!;
    } catch (err) {
      // 启动失败：回收半启动的子进程（否则它会变成占端口的孤儿）
      await this.killTree();
      throw err;
    }
  }

  // ------------------------------------------------------------------ //
  // 握手
  // ------------------------------------------------------------------ //
  private waitForHandshake(child: Electron.UtilityProcess): Promise<HandshakePayload> {
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
      // **D2**：握手期间进程退出必须**立刻**失败 —— 崩溃的 sidecar 不能干等到超时。
      // `utilityProcess` 不发 `error` 事件（Electron 主进程统一处理），只监听 `exit`。
      const onExit = (code: number) => {
        cleanup();
        reject(new Error(`后端在握手完成前退出：code=${code}`));
      };
      const cleanup = () => {
        clearTimeout(timer);
        child.stdout?.off("data", onData);
        child.off("exit", onExit);
      };
      child.stdout?.on("data", onData);
      child.once("exit", onExit);
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
    // **D9**：休眠时状态被置为 degraded → 这里若只认 "ready"，唤醒后探活**永久空转**。
    const st = backendState.current();
    if (!this.handshake || (st !== "ready" && st !== "degraded")) return;
    const ok = await this.ping(this.handshake.port, this.token);
    if (ok) {
      this.healthFails = 0;
      this.noteHealthySustained();
      return;
    }
    this.healthFails += 1;
    if (this.healthFails >= HEALTH_FAIL_THRESHOLD) {
      this.emitLog("健康探活连续失败，判定后端挂死");
      await this.restart("health-fail");
    }
  }

  /** 后端连续健康达到 HEALTHY_RESET_MS → 复位熔断计数（握手成功**不**复位）。 */
  private noteHealthySustained(): void {
    if (!this.healthySince) return;
    if (Date.now() - this.healthySince < HEALTHY_RESET_MS) return;
    this.healthySince = Date.now();
    backendState.resetConsecutiveFailures();
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
    this.emitLog(`后端退出：code=${code} signal=${signal ?? "-"}`);
    this.stopHealthLoop();
    this.childExited = true;
    this.child = null;
    this.handshake = null;
    this.healthySince = 0;
    if (backendState.current() === "stopping" || backendState.current() === "stopped") return;
    backendState.markCrashed(code !== 0 ? `exit code ${code}` : null);
    void this.restart("exit");
  }

  async restart(reason: string): Promise<void> {
    if (this.restarting) return;
    this.restarting = true;
    let failure: string | null = null;
    try {
      this.emitLog(`后端重启（原因：${reason}）`);
      // **D7**：熔断依据改为「连续失败次数」—— 握手成功不再清零，
      // 否则「起来→秒崩」永远达不到阈值 → 无限重启。
      if (backendState.status().consecutiveFailures >= RESTART_BREAKER_THRESHOLD) {
        backendState.set("degraded");
        this.emitLog("连续重启失败，已熔断；请查看日志");
        return;
      }
      backendState.noteRestart();
      const backoff = RESTART_BACKOFF_MS[
        Math.max(
          0,
          Math.min(
            backendState.status().consecutiveFailures - 1,
            RESTART_BACKOFF_MS.length - 1,
          ),
        )
      ];
      await sleep(backoff);
      await this.killTree();
      await this.start();
      // 重启后令牌更换，主窗口需重新引导
      const { rebootstrap } = await import("./window");
      rebootstrap();
    } catch (err) {
      failure = String(err);
      this.emitLog(`重启失败：${failure}`);
    } finally {
      this.restarting = false;
    }
    // 启动失败同样是一次失败：计入连续失败并继续重试（到熔断阈值为止）
    if (failure !== null) {
      backendState.markCrashed(failure);
      if (backendState.status().consecutiveFailures < RESTART_BREAKER_THRESHOLD) {
        this.retryTimer = setTimeout(
          () => void this.restart("retry"),
          RESTART_BACKOFF_MS[RESTART_BACKOFF_MS.length - 1],
        );
      } else {
        backendState.set("degraded");
        this.emitLog("连续重启失败，已熔断；请查看日志");
      }
    }
  }

  // ------------------------------------------------------------------ //
  // 优雅退出
  // ------------------------------------------------------------------ //
  async stop(): Promise<void> {
    backendState.set("stopping");
    this.stopHealthLoop();
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
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
    await this.killTree();
    // P6-07：**不**在这里删 run-state —— 本方法既用于「正常停止」，
    // 也用于「检测到 sidecar 崩溃后清理」；后者必须**保留** run-state
    // （其中的 pid 是下次启动回收孤儿的依据）。
    // 只有**应用正常退出**（before-quit）才删除。
    backendState.set("stopped");
  }

  // ------------------------------------------------------------------ //
  // 运行态记录（孤儿回收依据）
  // ------------------------------------------------------------------ //
  private writeRunState(port: number, pid: number, exe: string): void {
    try {
      const { runStatePath } = getPaths();
      fs.writeFileSync(
        runStatePath,
        // **D8**：记录 started_at 与可执行文件路径 → 回收前可校验 pid 归属
        JSON.stringify(
          { pid, port, started_at: new Date().toISOString(), exe },
          null,
          2,
        ),
        "utf-8",
      );
    } catch {
      // 记录失败不影响启动（下次启动无法回收孤儿，但不影响本次运行）
    }
  }

  /**
   * 删除 run-state.json。
   *
   * **P6-07**：**只在应用正常退出时调用**（`before-quit`）。
   * sidecar 异常终止（崩溃 / 被强杀）时**必须保留**该文件——
   * 其中的 pid 是下次启动 `cleanupOrphans()` 回收孤儿的依据。
   */
  clearRunState(): void {
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

  /**
   * 结束 sidecar。
   *
   * **改造要点（design/16 §4.3）**：`utilityProcess` 由 Electron 托管，
   * `child.kill()` 即可结束；Windows 保留 `taskkill /T /F` 兜底。
   */
  private async killTree(): Promise<void> {
    const child = this.child;
    if (!child || child.pid == null) return;
    const pid = child.pid;
    const exited = new Promise<void>((resolve) => {
      if (this.childExited) {
        resolve();
        return;
      }
      child.once("exit", () => resolve());
    });
    try {
      child.kill();
    } catch {
      // 进程可能已退出
    }
    // 侧车走优雅退出（跑完 shutdown：调度器 / MCP 会话回收），
    // 可能超出壳的退出等待窗口 → 超时后升级为强杀。
    await Promise.race([exited, sleep(2_000)]);
    if (!this.childExited) {
      if (process.platform === "win32") {
        try {
          spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
        } catch {
          // 进程可能已退出
        }
      } else {
        signalGroup(pid, "SIGKILL");
      }
      await Promise.race([exited, sleep(1_000)]);
    }
    this.child = null;
  }
}

/**
 * sidecar 入口标识（命令行里出现它即可确认归属）。
 *
 * **改造要点（design/16 §8.1）**：原为 Python 模块名 `app.desktop.launcher`，
 * 现改为 TS 入口文件名 `main.js`（配合 `run-state.exe` 记录的全路径）。
 */
const SIDECAR_MODULE = "main.js";

/** 给进程组发信号（POSIX：负 pid = 整个进程组）；失败则退回单进程。 */
function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch {
    try {
      process.kill(pid, signal);
    } catch {
      // 进程可能已退出
    }
  }
}

/** pid 是否还活着。 */
export function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM：进程存在，只是不属于当前用户
    return (err as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** 取进程的完整命令行（POSIX: ps；Windows: tasklist）。取不到 → null。 */
export function processCommandLine(pid: number): string | null {
  try {
    if (process.platform === "win32") {
      const out = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], {
        encoding: "utf-8",
        windowsHide: true,
      });
      if (out.status !== 0) return null;
      const line = (out.stdout ?? "").split(/\r?\n/).find((l) => l.trim().startsWith('"'));
      return line ? line.trim() : null;
    }
    const out = spawnSync("ps", ["-p", String(pid), "-o", "command="], { encoding: "utf-8" });
    if (out.status !== 0) return null;
    const text = (out.stdout ?? "").trim();
    return text.length > 0 ? text : null;
  } catch {
    return null;
  }
}

/**
 * 该 pid 是否就是本应用拉起的 sidecar（**归属校验**）。
 *
 * 依据：命令行里出现 sidecar 模块名，或出现 run-state 里记录的解释器全路径。
 * 都不匹配 → pid 已被系统回收并复用 → **绝不能**发信号（会误杀无关进程）。
 */
export function isOwnedBySidecar(record: RunStateRecord, cmdline: string | null): boolean {
  if (!cmdline) return false;
  if (cmdline.includes(SIDECAR_MODULE)) return true;
  if (record.exe && cmdline.includes(record.exe)) return true;
  if (record.exe && process.platform === "win32") {
    return cmdline.toLowerCase().includes(path.basename(record.exe).toLowerCase());
  }
  return false;
}

/** 读取 run-state.json（不存在 / 损坏 / 无有效 pid → null）。 */
export function readRunState(runStatePath: string): RunStateRecord | null {
  try {
    if (!fs.existsSync(runStatePath)) return null;
    const raw = JSON.parse(fs.readFileSync(runStatePath, "utf-8")) as Partial<RunStateRecord>;
    if (typeof raw?.pid !== "number" || !Number.isInteger(raw.pid) || raw.pid <= 0) return null;
    return {
      pid: raw.pid,
      ...(typeof raw.port === "number" ? { port: raw.port } : {}),
      ...(typeof raw.started_at === "string" ? { started_at: raw.started_at } : {}),
      ...(typeof raw.exe === "string" ? { exe: raw.exe } : {}),
    };
  } catch {
    return null;
  }
}

/** 等待 pid 消失（轮询）。 */
async function waitForExit(pid: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (!isProcessAlive(pid)) return true;
    if (Date.now() >= deadline) return false;
    await sleep(100);
  }
}

/**
 * 回收上次异常退出残留的 sidecar（**D8**）。
 *
 * 顺序很重要：SIGTERM → 轮询等待退出 → 超时升级 SIGKILL → **确认已退出**
 * 才允许删除 run-state（此前是 SIGTERM 后立刻删 → 侧车还活着却没了凭据，
 * 永远无法回收）。
 */
export async function reclaimOrphan(
  record: RunStateRecord,
  log?: (line: string) => void,
): Promise<ReclaimOutcome> {
  const pid = record.pid;
  if (!isProcessAlive(pid)) return "gone";
  const cmdline = processCommandLine(pid);
  if (!cmdline) {
    log?.(`孤儿回收：无法读取 pid=${pid} 的命令行 → 放弃（保留 run-state）`);
    return "alive";
  }
  if (!isOwnedBySidecar(record, cmdline)) {
    log?.(`孤儿回收：pid=${pid} 不属于本应用（${cmdline}）→ 放弃`);
    return "not-ours";
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // 已退出
  }
  if (await waitForExit(pid, 2_000)) return "killed";
  try {
    process.kill(pid, "SIGKILL");
  } catch {
    // 已退出
  }
  return (await waitForExit(pid, 1_000)) ? "killed" : "alive";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const supervisor = new BackendSupervisor();

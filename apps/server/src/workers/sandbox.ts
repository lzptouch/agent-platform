/**
 * 代码执行沙箱（design §7.4 · 双轨：Node 必备 + Python 可选）。
 *
 * 现状语义（`services/code_executor.py`，必须保持）：
 *
 * | 边界 | 实现 |
 * | --- | --- |
 * | 启动前 | 路径逃逸拦截 + 网络出口检测（默认关） |
 * | 运行中 | POSIX `setrlimit`（CPU 60s / 内存 1024MB / 句柄 256 / 单文件 64MB）+ 墙钟 180s + 输出上限 64KB（超出即杀） |
 * | 命令黑名单 | `BLOCKED_COMMANDS` 5 条 |
 * | 工作目录 | run 绑定的 workspace_root（运行期锁死）→ 回退全局工作区 → `data/outputs` |
 * | 写边界 | 仅 `cwd` + manifest `writable_roots` + `outputs` |
 *
 * Node 侧实现：POSIX 用 `ulimit`（`/bin/sh -c 'ulimit -t ... && exec ...'`），
 * Windows 保留 `taskkill /T /F` 兜底。
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { BLOCKED_COMMANDS, LIMITS, settings, type Settings } from "../shared/config.js";
import { getLogger } from "../shared/logger.js";

const logger = getLogger("workers.sandbox");

export interface ExecLimits {
  timeoutSeconds: number;
  cpuSeconds: number;
  memoryBytes: number;
  openFiles: number;
  fileSizeBytes: number;
  maxOutputBytes: number;
  resourceLimits: boolean;
}

/** 当前生效的资源限制。 */
export function limitsFromSettings(s: Settings = settings): ExecLimits {
  return {
    timeoutSeconds: s.exec_timeout,
    cpuSeconds: s.exec_cpu_seconds,
    memoryBytes: s.exec_memory_bytes,
    openFiles: s.exec_open_files,
    fileSizeBytes: s.exec_file_size_bytes,
    maxOutputBytes: s.exec_max_output_bytes,
    resourceLimits: s.exec_resource_limits,
  };
}

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  signal: string | null;
  timedOut: boolean;
  truncated: boolean;
  durationMs: number;
  /** 命中的限制（用于审计） */
  limitHit: string | null;
}

/** 命令黑名单命中检查。 */
export function isBlockedCommand(command: string): string | null {
  const normalized = command.trim();
  for (const blocked of BLOCKED_COMMANDS) {
    if (normalized.includes(blocked)) return blocked;
  }
  return null;
}

/** 路径逃逸检测：目标是否落在 root 之外。 */
export function detectEscape(target: string, root: string): boolean {
  const resolvedRoot = path.resolve(root);
  const resolved = path.resolve(resolvedRoot, target);
  return !(resolved === resolvedRoot || resolved.startsWith(resolvedRoot + path.sep));
}

/**
 * 构造带 POSIX 资源限制的命令前缀。
 *
 * `ulimit -t`（CPU 秒）、`-v`（虚拟内存 KB）、`-n`（句柄）、`-f`（单文件 512B 块）。
 */
export function buildRlimitPrefix(limits: ExecLimits): string {
  if (!limits.resourceLimits || process.platform === "win32") return "";
  const memKb = Math.floor(limits.memoryBytes / 1024);
  const fileBlocks = Math.floor(limits.fileSizeBytes / 512);
  return [
    `ulimit -t ${limits.cpuSeconds} 2>/dev/null || true`,
    `ulimit -v ${memKb} 2>/dev/null || true`,
    `ulimit -n ${limits.openFiles} 2>/dev/null || true`,
    `ulimit -f ${fileBlocks} 2>/dev/null || true`,
  ].join("; ");
}

export interface RunOptions {
  cwd: string;
  timeoutSeconds?: number;
  env?: Record<string, string>;
  /** 输入（stdin） */
  stdin?: string;
}

/**
 * 执行一条 shell 命令（带超时与输出上限）。
 *
 * 输出超过 `maxOutputBytes` → **立即杀掉进程**（与 Python 侧一致）。
 */
export function runCommand(
  command: string,
  opts: RunOptions,
  limits: ExecLimits = limitsFromSettings(),
): Promise<ExecResult> {
  const timeoutSeconds = opts.timeoutSeconds ?? limits.timeoutSeconds;
  const started = Date.now();
  const prefix = buildRlimitPrefix(limits);
  const fullCommand = prefix ? `${prefix}; exec ${command}` : command;

  return new Promise<ExecResult>((resolve) => {
    const isWin = process.platform === "win32";
    const shell = isWin ? "cmd.exe" : "/bin/sh";
    const args = isWin ? ["/d", "/s", "/c", command] : ["-c", fullCommand];

    const child = spawn(shell, args, {
      cwd: opts.cwd,
      env: { ...process.env, ...(opts.env ?? {}) },
      detached: !isWin, // 独立进程组 → 可整组 kill
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let truncated = false;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child.pid);
    }, timeoutSeconds * 1000);

    child.stdout?.on("data", (chunk: Buffer) => {
      if (stdout.length + chunk.length > limits.maxOutputBytes) {
        truncated = true;
        killTree(child.pid);
        return;
      }
      stdout += chunk.toString("utf-8");
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length + chunk.length > limits.maxOutputBytes) {
        truncated = true;
        killTree(child.pid);
        return;
      }
      stderr += chunk.toString("utf-8");
    });

    if (opts.stdin !== undefined) {
      child.stdin?.write(opts.stdin);
      child.stdin?.end();
    } else {
      child.stdin?.end();
    }

    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({
        stdout,
        stderr: `${stderr}${err.message}`,
        exitCode: null,
        signal: null,
        timedOut,
        truncated,
        durationMs: Date.now() - started,
        limitHit: truncated ? "max_output_bytes" : null,
      });
    });

    child.on("close", (code, signal) => {
      clearTimeout(timer);
      resolve({
        stdout,
        stderr,
        exitCode: code,
        signal,
        timedOut,
        truncated,
        durationMs: Date.now() - started,
        limitHit: truncated ? "max_output_bytes" : timedOut ? "timeout" : null,
      });
    });
  });
}

/** 杀掉整个进程组（POSIX）/ 进程树（Windows）。 */
export function killTree(pid: number | undefined): void {
  if (!pid) return;
  if (process.platform === "win32") {
    try {
      spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      // 忽略
    }
    return;
  }
  try {
    // 负号 → 进程组
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // 忽略
    }
  }
}

/** 写一个临时脚本文件并执行（Python / Node 轨道）。 */
export async function runScript(
  language: "python" | "javascript",
  code: string,
  opts: RunOptions,
  limits: ExecLimits = limitsFromSettings(),
): Promise<ExecResult> {
  const isPython = language === "python";
  const ext = isPython ? ".py" : ".mjs";
  const file = path.join(opts.cwd, `.agent_exec_${Date.now()}${ext}`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, code, "utf-8");
  try {
    if (isPython) {
      const pythonBin = detectPython();
      if (!pythonBin) {
        return {
          stdout: "",
          stderr:
            "未检测到 Python 解释器。Python 代码执行不可用。\n" +
            "可改用 JavaScript，或在 设置 → Python 运行时 中下载/指定。",
          exitCode: null,
          signal: null,
          timedOut: false,
          truncated: false,
          durationMs: 0,
          limitHit: "python_missing",
        };
      }
      return await runCommand(`${quote(pythonBin)} ${quote(file)}`, opts, limits);
    }
    return await runCommand(`${quote(process.execPath)} ${quote(file)}`, opts, limits);
  } finally {
    try {
      fs.rmSync(file, { force: true });
    } catch {
      // 忽略
    }
  }
}

/** 引号包裹（POSIX 单引号转义）。 */
export function quote(value: string): string {
  if (process.platform === "win32") return `"${value}"`;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** 探测 Python 解释器（AGENT_PYTHON_BIN → userData runtime → 系统 python3）。 */
export function detectPython(s: Settings = settings): string | null {
  const candidates = [
    process.env.AGENT_PYTHON_BIN,
    path.join(s.user_data_dir, "runtime", "python", "bin", "python3"),
    path.join(s.user_data_dir, "runtime", "python", "python.exe"),
    "/usr/bin/python3",
    "/usr/local/bin/python3",
    "/opt/homebrew/bin/python3",
  ].filter(Boolean) as string[];
  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      // 忽略
    }
  }
  return null;
}

/** 代码执行前的路径逃逸拦截。 */
export function checkPathAllowed(
  target: string,
  roots: string[],
  forWrite = false,
): string | null {
  if (!roots.length) return null;
  const resolved = path.resolve(target);
  for (const root of roots) {
    const resolvedRoot = path.resolve(root);
    if (resolved === resolvedRoot || resolved.startsWith(resolvedRoot + path.sep)) {
      return null;
    }
  }
  return forWrite
    ? `路径超出允许范围: ${target}`
    : `路径超出允许范围: ${target}`;
}

/** 审计日志（写边界命中时）。 */
export function auditLimit(kind: string, detail: Record<string, unknown>): void {
  logger.warn("执行边界命中", { kind, ...detail });
}

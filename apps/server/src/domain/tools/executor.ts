/**
 * 本地代码执行器（契约对齐：services/code_executor.py 的 `LocalCodeExecutor`）。
 *
 * 执行边界：
 * - 启动前：工作目录逃逸拦截 + 网络出口开关（默认关）；
 * - 运行中：CPU / 内存 / 句柄 / 单文件大小限制（POSIX）+ 墙钟超时 + 输出上限；
 * - 每次限制命中都写审计。
 */
import fs from "node:fs";
import path from "node:path";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { getWorkspaceDir } from "../workspace/service.js";
import {
  auditLimit,
  checkPathAllowed,
  isBlockedCommand,
  limitsFromSettings,
  runCommand,
  runScript,
  type ExecLimits,
} from "../../workers/sandbox.js";

const logger = getLogger("exec.executor");

/** 当前 run 绑定的上下文（运行期锁死）。 */
let currentRunContext: { workspace_id?: string | null; workspace_root?: string | null } | null =
  null;

export function setCurrentRunContext(
  ctx: { workspace_id?: string | null; workspace_root?: string | null } | null,
): void {
  currentRunContext = ctx;
}

export function getCurrentRunContext(): typeof currentRunContext {
  return currentRunContext;
}

/** matplotlib 预处理：强制 Agg 后端 + 中文字体。 */
export const MPL_PREAMBLE = [
  "import matplotlib as _mpl",
  "_mpl.use('Agg')",
  "_mpl.rcParams['font.sans-serif'] = ['PingFang HK', 'Heiti TC', 'Arial Unicode MS', 'STHeiti', 'SimSong']",
  "_mpl.rcParams['axes.unicode_minus'] = False",
].join("\n");

export class LocalCodeExecutor {
  readonly outputDir: string;
  readonly timeout: number;
  private readonly s: Settings;

  constructor(outputDir?: string, timeout?: number, s: Settings = settings) {
    this.s = s;
    this.outputDir = outputDir ?? s.output_dir;
    this.timeout = (timeout ?? s.exec_timeout) as number;
    fs.mkdirSync(this.outputDir, { recursive: true });
  }

  /** 当前生效的资源限制。 */
  limits(): ExecLimits {
    return limitsFromSettings(this.s);
  }

  /**
   * 命令执行的工作目录。
   *
   * **优先取本次 run 绑定的** `workspace_root`（运行期锁死）；无 run 上下文时
   * 回落全局当前空间，再回落 `data/outputs`。
   */
  cwdDir(): string {
    const ctx = currentRunContext;
    if (ctx?.workspace_root) {
      const bound = String(ctx.workspace_root);
      if (fs.existsSync(bound)) return bound;
    }
    try {
      const workspace = getWorkspaceDir();
      if (workspace && fs.existsSync(workspace)) return workspace;
    } catch {
      // 解析失败不应阻断执行
    }
    return this.outputDir;
  }

  /** 文件工具允许访问的根目录（写操作全形态生效）。 */
  allowedRoots(): string[] {
    const roots = [this.cwdDir()];
    const out = this.outputDir;
    if (!roots.includes(out)) roots.push(out);
    return roots;
  }

  /** 校验路径是否在允许范围内；返回错误说明（null 表示放行）。 */
  checkAllowed(target: string, forWrite = false): string | null {
    const roots = forWrite || this.s.desktop_mode ? this.allowedRoots() : [];
    if (!roots.length) return null;
    return checkPathAllowed(path.resolve(this.cwdDir(), target), roots, forWrite);
  }

  /** 执行一条 Bash 命令。 */
  async executeBash(command: string): Promise<Record<string, unknown>> {
    const blocked = isBlockedCommand(command);
    if (blocked) {
      auditLimit("blocked_command", { command, pattern: blocked });
      return {
        ok: false,
        stdout: "",
        stderr: `命令被安全策略拒绝（命中黑名单: ${blocked}）`,
        exit_code: null,
      };
    }
    const result = await runCommand(command, { cwd: this.cwdDir() }, this.limits());
    if (result.limitHit) {
      auditLimit(result.limitHit, { command, durationMs: result.durationMs });
    }
    return {
      ok: result.exitCode === 0 && !result.timedOut,
      stdout: result.stdout,
      stderr: result.stderr,
      exit_code: result.exitCode,
      timed_out: result.timedOut,
      truncated: result.truncated,
      duration_ms: result.durationMs,
    };
  }

  /** 执行一段 Python 代码。 */
  async executePython(code: string): Promise<Record<string, unknown>> {
    const full = code.includes("matplotlib")
      ? `${MPL_PREAMBLE}\n${code}`
      : code;
    const result = await runScript("python", full, { cwd: this.cwdDir() }, this.limits());
    if (result.limitHit) {
      auditLimit(result.limitHit, { language: "python", durationMs: result.durationMs });
    }
    return {
      ok: result.exitCode === 0 && !result.timedOut,
      stdout: result.stdout,
      stderr: result.stderr,
      exit_code: result.exitCode,
      timed_out: result.timedOut,
      truncated: result.truncated,
      duration_ms: result.durationMs,
      limit_hit: result.limitHit,
    };
  }

  /** 执行一段 JavaScript 代码（Node 轨道，永远可用）。 */
  async executeJavaScript(code: string): Promise<Record<string, unknown>> {
    const result = await runScript("javascript", code, { cwd: this.cwdDir() }, this.limits());
    if (result.limitHit) {
      auditLimit(result.limitHit, { language: "javascript", durationMs: result.durationMs });
    }
    return {
      ok: result.exitCode === 0 && !result.timedOut,
      stdout: result.stdout,
      stderr: result.stderr,
      exit_code: result.exitCode,
      timed_out: result.timedOut,
      truncated: result.truncated,
      duration_ms: result.durationMs,
      limit_hit: result.limitHit,
    };
  }
}

/** 全局执行器单例。 */
export const codeExecutor = new LocalCodeExecutor();

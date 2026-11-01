/**
 * 结构化日志（契约对齐：backend/app/core/logging.py）。
 *
 * - JSON 行格式（每行一条 JSON），便于按 `request_id` 检索；
 * - 落盘文件轮转（`log_file_max_bytes` / `log_file_backup_count`）；
 * - DEBUG 级采样（`log_debug_sample_rate`），ERROR 及以上全量。
 */
import fs from "node:fs";
import path from "node:path";
import { getRequestId } from "./errors.js";
import { settings, type Settings } from "./config.js";

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR";

const LEVEL_ORDER: Record<LogLevel, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
};

export interface LogRecord {
  ts: string;
  level: LogLevel;
  logger: string;
  message: string;
  request_id?: string;
  [key: string]: unknown;
}

/** 采样计数器（按 logger 维度）。 */
const debugSampled = new Map<string, boolean>();

function shouldEmit(level: LogLevel, scope: string, s: Settings): boolean {
  if (level === "DEBUG") {
    const cached = debugSampled.get(scope);
    if (cached !== undefined) return cached;
    const hit = Math.random() < s.log_debug_sample_rate;
    debugSampled.set(scope, hit);
    return hit;
  }
  return true;
}

function rotateIfNeeded(filePath: string, s: Settings): void {
  try {
    if (!fs.existsSync(filePath)) return;
    const stat = fs.statSync(filePath);
    if (stat.size < s.log_file_max_bytes) return;
    for (let i = s.log_file_backup_count - 1; i >= 1; i -= 1) {
      const from = `${filePath}.${i}`;
      const to = `${filePath}.${i + 1}`;
      if (fs.existsSync(from)) fs.renameSync(from, to);
    }
    fs.renameSync(filePath, `${filePath}.1`);
  } catch {
    // 轮转失败不阻断日志输出
  }
}

export class Logger {
  private readonly scope: string;
  private readonly s: Settings;
  private stream: fs.WriteStream | null = null;

  constructor(scope: string, s: Settings = settings) {
    this.scope = scope;
    this.s = s;
  }

  private write(level: LogLevel, message: string, extra?: Record<string, unknown>): void {
    if (!shouldEmit(level, this.scope, this.s)) return;
    const threshold = LEVEL_ORDER[(this.s.log_file_level as LogLevel) ?? "DEBUG"] ?? 10;
    if (LEVEL_ORDER[level] < threshold) return;

    const record: LogRecord = {
      ts: new Date().toISOString(),
      level,
      logger: this.scope,
      message,
      request_id: getRequestId(),
      ...(extra ?? {}),
    };
    const line = `${JSON.stringify(record)}\n`;

    // stderr：与 Python 侧一致（stdout 留给握手行）
    process.stderr.write(line);

    if (this.s.log_to_file) {
      try {
        if (!this.stream) {
          fs.mkdirSync(this.s.logs_dir, { recursive: true });
          rotateIfNeeded(path.join(this.s.logs_dir, this.s.log_file_name), this.s);
          this.stream = fs.createWriteStream(
            path.join(this.s.logs_dir, this.s.log_file_name),
            { flags: "a" },
          );
          this.stream.on("error", () => {
            this.stream = null;
          });
        }
        this.stream.write(line);
      } catch {
        // 落盘失败不阻断
      }
    }
  }

  debug(message: string, extra?: Record<string, unknown>): void {
    this.write("DEBUG", message, extra);
  }
  info(message: string, extra?: Record<string, unknown>): void {
    this.write("INFO", message, extra);
  }
  warn(message: string, extra?: Record<string, unknown>): void {
    this.write("WARNING", message, extra);
  }
  error(message: string, extra?: Record<string, unknown>): void {
    this.write("ERROR", message, extra);
  }
}

const loggers = new Map<string, Logger>();

/** 获取（并缓存）某个 scope 的 logger。 */
export function getLogger(scope: string): Logger {
  let logger = loggers.get(scope);
  if (!logger) {
    logger = new Logger(scope);
    loggers.set(scope, logger);
  }
  return logger;
}

/** 关闭所有日志流（进程退出时调用）。 */
export function closeLoggers(): void {
  for (const logger of loggers.values()) {
    (logger as unknown as { stream: fs.WriteStream | null }).stream?.end();
  }
}

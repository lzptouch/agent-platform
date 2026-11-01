/**
 * 统一错误模型与请求 ID（契约冻结项，来源：backend/app/core/errors.py）。
 *
 * 设计要点：
 * - **一个错误体**：`{code, message, detail, request_id}`，所有失败路径一致；
 * - **请求 ID 全链路贯通**：入口中间件生成或透传 `X-Request-ID`，写入
 *   `AsyncLocalStorage`，错误体与响应头都带它，便于日志检索；
 * - **错误码枚举与 HTTP 状态映射**逐条对齐 Python 侧（见 contract/errors.json）。
 */
import { randomUUID } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";

export const REQUEST_ID_HEADER = "X-Request-ID";

/** 请求 ID 上下文（替代 Python 的 contextvars）。 */
const requestIdStore = new AsyncLocalStorage<string>();

/** 允许出现在 request id 中的字符（其余一律剔除）。 */
const RID_SAFE = /[^A-Za-z0-9._-]/g;
/** request id 最大长度。 */
const RID_MAX_LEN = 64;

// --------------------------------------------------------------------------- //
// 错误码
// --------------------------------------------------------------------------- //
export const ErrorCode = {
  VALIDATION: "E_VALIDATION",
  NOT_FOUND: "E_NOT_FOUND",
  CONFLICT: "E_CONFLICT",
  AUTH: "E_AUTH",
  PERMISSION: "E_PERMISSION",
  RUN: "E_RUN",
  WORKSPACE: "E_WORKSPACE",
  MCP: "E_MCP",
  SCHEDULER: "E_SCHEDULER",
  FILE: "E_FILE",
  UPSTREAM: "E_UPSTREAM",
  INTERNAL: "E_INTERNAL",
  TOO_LARGE: "E_TOO_LARGE",
} as const;

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode];

export const ERROR_CODES: ErrorCodeValue[] = Object.values(ErrorCode);

/** HTTP 状态 → 业务错误码（与 Python `ErrorCode.from_status` 逐条一致）。 */
const STATUS_TO_CODE: Record<number, ErrorCodeValue> = {
  400: ErrorCode.VALIDATION,
  401: ErrorCode.AUTH,
  403: ErrorCode.PERMISSION,
  404: ErrorCode.NOT_FOUND,
  409: ErrorCode.CONFLICT,
  413: ErrorCode.TOO_LARGE,
  415: ErrorCode.VALIDATION,
  421: ErrorCode.AUTH,
  422: ErrorCode.VALIDATION,
  500: ErrorCode.INTERNAL,
  502: ErrorCode.UPSTREAM,
  503: ErrorCode.UPSTREAM,
};

export function errorCodeFromStatus(statusCode: number): ErrorCodeValue {
  return STATUS_TO_CODE[statusCode] ?? ErrorCode.INTERNAL;
}

// --------------------------------------------------------------------------- //
// 业务异常
// --------------------------------------------------------------------------- //
export class AppError extends Error {
  readonly code: string;
  readonly statusCode: number;
  readonly detail: unknown;

  constructor(
    code: string,
    message: string,
    opts: { statusCode?: number; detail?: unknown } = {},
  ) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.statusCode = opts.statusCode ?? 400;
    this.detail = opts.detail ?? null;
  }
}

/** 语义等价于 FastAPI 的 `HTTPException`（统一错误体 + 状态码）。 */
export class HttpError extends Error {
  readonly statusCode: number;
  readonly detail: unknown;
  readonly headers: Record<string, string>;

  constructor(
    statusCode: number,
    detail: unknown,
    headers: Record<string, string> = {},
  ) {
    super(typeof detail === "string" ? detail : "请求失败");
    this.name = "HttpError";
    this.statusCode = statusCode;
    this.detail = detail;
    this.headers = headers;
  }
}

// --------------------------------------------------------------------------- //
// 请求 ID
// --------------------------------------------------------------------------- //
export function newRequestId(): string {
  return randomUUID().replace(/-/g, "").slice(0, 16);
}

/**
 * 设置（并返回）当前请求的 id。
 *
 * **安全**：客户端提供的 `X-Request-ID` 被限长 64 + 只保留 `[A-Za-z0-9._-]`；
 * 非法则重新生成（防日志注入 / 响应头注入）。
 */
export function sanitizeRequestId(value: string | undefined | null): string {
  const cleaned = (value ?? "").trim().replace(RID_SAFE, "").slice(0, RID_MAX_LEN);
  return cleaned || newRequestId();
}

/** 在当前请求上下文中设置 request id。 */
export function setRequestId(value: string | undefined | null): string {
  const rid = sanitizeRequestId(value);
  requestIdStore.enterWith(rid);
  return rid;
}

/** 取当前请求 id（无值时生成新的）。 */
export function getRequestId(): string {
  return requestIdStore.getStore() ?? newRequestId();
}

/** 在指定 request id 上下文中执行（供 SSE 等需要显式绑定的场景）。 */
export function runWithRequestId<T>(rid: string, fn: () => T): T {
  return requestIdStore.run(rid, fn);
}

// --------------------------------------------------------------------------- //
// 统一响应体
// --------------------------------------------------------------------------- //
export interface ErrorBody {
  code: string;
  message: string;
  detail: unknown;
  request_id: string;
}

export function errorBody(
  code: string,
  message: string,
  detail: unknown = null,
  requestId?: string,
): ErrorBody {
  return {
    code,
    message,
    detail: detail ?? null,
    request_id: requestId ?? getRequestId(),
  };
}

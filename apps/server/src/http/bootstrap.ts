/**
 * 桌面会话引导与访问边界（契约冻结，来源：backend/app/desktop/bootstrap.py）。
 *
 * 安全模型（design/04 §5.2）：
 * - **一次性引导 nonce**：`GET /__desktop/bootstrap?t=<nonce>` 校验通过即作废，
 *   下发 HttpOnly + SameSite=Strict 的会话 Cookie 后 302 回 `/`；
 * - **常驻会话令牌**：`X-Agent-Desktop-Token` header，供壳自身的 Node 侧请求使用，
 *   **永不出现在 URL**；
 * - **Host 头白名单**：只接受 `127.0.0.1` / `localhost` 且端口等于本进程端口，
 *   防 DNS rebinding。
 */
import crypto from "node:crypto";
import { settings, type Settings } from "../shared/config.js";
import { getLogger } from "../shared/logger.js";

const logger = getLogger("desktop.bootstrap");

export const COOKIE_NAME = "agent_desktop_session";
export const HEADER_NAME = "X-Agent-Desktop-Token";

/** 允许的 Host 主机名（端口必须与本进程一致）。 */
export const ALLOWED_HOSTNAMES = new Set(["127.0.0.1", "localhost"]);

/** 会话 ID 的有效期（秒）。超过后必须重新引导。 */
export const SESSION_TTL_SECONDS = 8 * 3600;

interface SessionState {
  sessionId: string | null;
  sessionIssuedAt: number;
  nonceConsumed: boolean;
}

const state: SessionState = {
  sessionId: null,
  sessionIssuedAt: 0,
  nonceConsumed: false,
};

/** 常量时间比较（等价 `hmac.compare_digest`）。 */
export function timingSafeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a, "utf-8");
  const bufB = Buffer.from(b, "utf-8");
  if (bufA.length !== bufB.length) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

/**
 * 签发会话 ID。
 *
 * **独立随机**生成（不再由令牌派生）→ Cookie 值无法反推令牌。
 */
export function issueSession(s: Settings = settings): string {
  if (!s.desktop_token) {
    throw new Error("桌面模式未注入 AGENT_DESKTOP_TOKEN");
  }
  const sessionId = crypto.randomBytes(32).toString("base64url");
  state.sessionId = sessionId;
  state.sessionIssuedAt = Date.now() / 1000;
  return sessionId;
}

/** 当前会话 ID。 */
export function currentSessionId(): string | null {
  return state.sessionId;
}

/** 清空会话状态（测试用）。 */
export function resetState(): void {
  state.sessionId = null;
  state.sessionIssuedAt = 0;
  state.nonceConsumed = false;
}

/** 校验并作废一次性引导 nonce。 */
export function consumeNonce(candidate: string, s: Settings = settings): boolean {
  const expected = s.desktop_bootstrap_nonce;
  if (!expected || !candidate) return false;
  if (state.nonceConsumed) return false;
  // 非 ASCII 输入直接判失败（避免常量时间比较抛错）
  if (!/^[\x00-\x7F]*$/.test(candidate)) return false;
  if (!timingSafeEqual(candidate, expected)) return false;
  state.nonceConsumed = true;
  return true;
}

/** Host 头白名单：仅接受 loopback + 正确端口。 */
export function hostAllowed(hostHeader: string | undefined, s: Settings = settings): boolean {
  const raw = (hostHeader ?? "").trim();
  if (!raw) return false;
  let host: string;
  let port: string;
  if (raw.startsWith("[")) {
    // IPv6 字面量
    const idx = raw.lastIndexOf("]:");
    if (idx < 0) return false;
    host = raw.slice(1, idx);
    port = raw.slice(idx + 2);
  } else {
    const idx = raw.lastIndexOf(":");
    if (idx < 0) {
      host = raw;
      port = "";
    } else {
      host = raw.slice(0, idx);
      port = raw.slice(idx + 1);
    }
  }
  if (!ALLOWED_HOSTNAMES.has(host)) return false;
  if (!port) return false;
  return port === String(s.port);
}

/** 校验会话：Cookie 或 Header 令牌任一通过即可。 */
export function requestAuthorized(
  headerValue: string | undefined,
  cookieValue: string | undefined,
  s: Settings = settings,
): boolean {
  const token = s.desktop_token;
  if (!token) return false;

  if (headerValue && /^[\x00-\x7F]*$/.test(headerValue) && timingSafeEqual(headerValue, token)) {
    return true;
  }

  if (cookieValue && /^[\x00-\x7F]*$/.test(cookieValue)) {
    const sessionId = state.sessionId;
    if (sessionId && timingSafeEqual(cookieValue, sessionId)) {
      const issuedAt = state.sessionIssuedAt || 0;
      // fail-closed：签发时间缺失 / 为 0 时一律视为过期
      if (!issuedAt || Date.now() / 1000 - issuedAt > SESSION_TTL_SECONDS) {
        logger.info("桌面会话已过期或签发时间缺失，需重新引导");
        return false;
      }
      return true;
    }
  }
  return false;
}

/** 引导端点的处理结果。 */
export type BootstrapResult =
  | { ok: true; sessionId: string }
  | { ok: false; statusCode: number; detail: string };

/** 处理引导请求：校验 nonce → 下发 Cookie → 302 回首页。 */
export function handleBootstrap(
  nonce: string,
  s: Settings = settings,
): BootstrapResult {
  if (!consumeNonce(nonce, s)) {
    logger.warn("桌面引导令牌无效或已使用");
    return { ok: false, statusCode: 401, detail: "引导令牌无效或已使用" };
  }
  const sessionId = issueSession(s);
  return { ok: true, sessionId };
}

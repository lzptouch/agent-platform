/** 握手与进程编排的共享常量。 */

/** 后端 stdout 中握手行的前缀。 */
export const HANDSHAKE_PREFIX = "AGENT_DESKTOP_READY ";

/** 握手超时（毫秒）。 */
export const HANDSHAKE_TIMEOUT_MS = 90_000;

/** 健康探活间隔（毫秒）。 */
export const HEALTH_INTERVAL_MS = 30_000;

/** 健康探活连续失败阈值（超过则判定为挂死 → 重启）。 */
export const HEALTH_FAIL_THRESHOLD = 3;

/** 崩溃重启的熔断阈值（连续失败次数）。 */
export const RESTART_BREAKER_THRESHOLD = 3;

/** 崩溃重启的退避序列（毫秒）。 */
export const RESTART_BACKOFF_MS = [1_000, 2_000, 4_000];

/** 注入给后端的环境变量名。 */
export const ENV = {
  desktop: "AGENT_DESKTOP",
  token: "AGENT_DESKTOP_TOKEN",
  bootstrapNonce: "AGENT_DESKTOP_BOOTSTRAP_NONCE",
  protocol: "AGENT_DESKTOP_PROTOCOL",
  dataDir: "AGENT_DATA_DIR",
  workspaceDir: "AGENT_WORKSPACE_DIR",
  frontendDist: "AGENT_FRONTEND_DIST",
  missedWindowHours: "AGENT_DESKTOP_MISSED_WINDOW_HOURS",
  playwrightBrowsersPath: "PLAYWRIGHT_BROWSERS_PATH",
} as const;

/** 引导与探针的固定路径。 */
export const PATHS = {
  bootstrap: "/__desktop/bootstrap",
  ping: "/__desktop/ping",
  health: "/api/v1/health",
  events: "/api/v1/desktop/events",
  shutdown: "/api/v1/desktop/shutdown",
} as const;

/** 握手载荷（后端 → 壳）。 */
export interface HandshakePayload {
  protocol: number;
  port: number;
  pid: number;
  data_dir: string;
  workspace_dir: string;
  app_version: string;
  backend_version: string;
  started_at: string;
}

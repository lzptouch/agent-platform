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

/**
 * 后端需**持续健康**多久才复位「连续失败」计数（毫秒）。
 *
 * 熔断计数**不能**在握手成功时清零：后端「起来 → 秒崩」时每次握手都成功，
 * 一清零就等于熔断永不触发。只有连续健康超过该时长，才认为这次启动真的稳住了。
 */
export const HEALTHY_RESET_MS = 60_000;

/** 补跑窗口（小时）：休眠唤醒后补跑错过任务的时间范围。 */
export const MISSED_WINDOW_HOURS = 6;

/** 补跑窗口小时数注入后端用的环境变量名（后端读它 → desktop_missed_window_hours）。 */
export const ENV_MISSED_WINDOW_HOURS = "AGENT_DESKTOP_MISSED_WINDOW_HOURS";

/** 注入给后端的环境变量名。 */
export const ENV = {
  desktop: "AGENT_DESKTOP",
  token: "AGENT_DESKTOP_TOKEN",
  bootstrapNonce: "AGENT_DESKTOP_BOOTSTRAP_NONCE",
  protocol: "AGENT_DESKTOP_PROTOCOL",
  dataDir: "AGENT_DATA_DIR",
  workspaceDir: "AGENT_WORKSPACE_DIR",
  frontendDist: "AGENT_FRONTEND_DIST",
  /**
   * TS 后端入口路径（design/16 §8.5）。
   *
   * 后端已由 Python 重写为 TypeScript → 壳用 `utilityProcess.fork()` 加载它，
   * 不再需要 Python 解释器路径。
   */
  serverEntry: "AGENT_SERVER_ENTRY",
  playwrightBrowsersPath: "PLAYWRIGHT_BROWSERS_PATH",
} as const;

/** 引导与探针的固定路径。 */
export const PATHS = {
  bootstrap: "/__desktop/bootstrap",
  ping: "/__desktop/ping",
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

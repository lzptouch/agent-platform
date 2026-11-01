/**
 * sidecar 入口（契约对齐：backend/app/desktop/launcher.py）。
 *
 * 职责：
 * 1. **自绑 loopback 套接字**（端口由 OS 分配）→ 消除 TOCTOU 竞态；
 * 2. **打印一行握手**：`AGENT_DESKTOP_READY {json}`，壳据此拿到真实端口与路径；
 * 3. 启动 Fastify 服务。
 *
 * 环境变量（由壳注入）：
 * - `AGENT_DESKTOP=1` · `AGENT_DESKTOP_TOKEN` · `AGENT_DESKTOP_BOOTSTRAP_NONCE`
 * - `AGENT_DATA_DIR` · `AGENT_FRONTEND_DIST`
 */
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { settings, ensureDirs } from "./shared/config.js";
import { getLogger, closeLoggers } from "./shared/logger.js";
import { buildApp } from "./http/app.js";
import { initDb } from "./db/client.js";
import { runMigrations } from "./db/migrate.js";
import { getServices, closeServices } from "./http/context.js";

/** 后端 stdout 中握手行的前缀（**协议不变**）。 */
export const HANDSHAKE_PREFIX = "AGENT_DESKTOP_READY ";

const BIND_RETRIES = 5;
const BIND_RETRY_DELAY_MS = 100;

const logger = getLogger("main");

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

/** 组装握手载荷（**不含令牌**）。 */
export function buildHandshake(port: number): HandshakePayload {
  return {
    protocol: settings.desktop_protocol,
    port,
    pid: process.pid,
    data_dir: settings.user_data_dir,
    workspace_dir: settings.default_workspace_dir,
    app_version: settings.app_name,
    backend_version: settings.app_version,
    started_at: new Date().toISOString(),
  };
}

/** 绑定一个由 OS 分配端口的 loopback 套接字。 */
export function bindLoopback(
  retries = BIND_RETRIES,
): Promise<net.Server> {
  return new Promise((resolve, reject) => {
    let attempt = 0;
    const tryBind = (): void => {
      const server = net.createServer();
      server.once("error", (err) => {
        attempt += 1;
        if (attempt >= retries) {
          reject(new Error(`无法绑定本地端口（重试 ${retries} 次）：${err.message}`));
          return;
        }
        logger.warn("绑定本地端口失败", { attempt, error: err.message });
        setTimeout(tryBind, BIND_RETRY_DELAY_MS);
      });
      server.listen({ host: "127.0.0.1", port: 0, backlog: 2048 }, () => {
        resolve(server);
      });
    };
    tryBind();
  });
}

/** 启动服务。 */
export async function main(): Promise<void> {
  if (!settings.desktop_mode) {
    logger.warn("AGENT_DESKTOP 未开启，以普通模式启动（桌面握手仍可用）");
  }

  // 目录 → 迁移 → 服务
  ensureDirs();
  initDb();
  runMigrations();

  const services = getServices();
  services.permission.ensureBuiltinRules();
  const sync = services.skill.syncToDb();
  if (sync.warnings.length) logger.warn("Skill 同步告警", { warnings: sync.warnings });
  logger.info("已加载 Skill", { count: sync.synced });
  if (!settings.has_api_key) {
    logger.warn("未配置 DASHSCOPE_API_KEY —— /api/v1/agent/run 将返回错误提示");
  }

  // **端口由 OS 分配**（`port: 0`）→ 无 TOCTOU 竞态（与 Python 侧 `bind(0)` 语义一致）
  // 开发态可用 `AGENT_PORT` 固定端口（Vite dev proxy 指向该端口）。
  const devPort = Number(process.env.AGENT_PORT ?? 0) || 0;
  const app = await buildApp();
  await app.listen({ host: "127.0.0.1", port: devPort });
  const address = app.server.address();
  const port = typeof address === "object" && address ? address.port : settings.port;
  // 桌面守卫依赖 `settings.port` 做 Host 白名单校验
  (settings as unknown as { port: number }).port = port;

  logger.info("桌面 sidecar 启动", { port, pid: process.pid });

  // 握手行 → stdout（**唯一写 stdout 的地方**）
  process.stdout.write(HANDSHAKE_PREFIX + JSON.stringify(buildHandshake(port)) + "\n");

  const shutdown = async (): Promise<void> => {
    logger.info("收到退出信号，开始优雅关闭");
    try {
      await app.close();
    } catch {
      // 忽略
    }
    try {
      await closeServices();
    } catch {
      // 忽略
    }
    closeLoggers();
    process.exit(0);
  };

  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());
}

/**
 * 入口判定：**必须用 `fileURLToPath` 反解 URL**，不能直接拿 `import.meta.url` 比较。
 *
 * **P8-01 实测踩坑**：打包产物路径含**空格**（`Agent Desktop.app`）时，
 * `import.meta.url` 会把空格编码成 `%20`，而 `process.argv[1]` 是**原始空格**
 * → `endsWith()` 恒为 false → **`main()` 从不执行** → sidecar 静默退出（exit 0、
 * 无任何日志）。开发态路径无空格，所以问题只在安装包里暴露。
 *
 * @param argv1 `process.argv[1]`（可为空）
 * @param metaUrl `import.meta.url`
 */
export function isEntryPoint(argv1: string | undefined, metaUrl: string): boolean {
  if (!argv1) return false;
  try {
    return path.resolve(argv1) === fileURLToPath(metaUrl);
  } catch {
    return false;
  }
}

const isEntry = isEntryPoint(process.argv[1], import.meta.url);
if (isEntry || process.env.AGENT_FORCE_START === "1") {
  main().catch((err) => {
    logger.error("启动失败", { error: String(err) });
    // 打印完整堆栈（便于定位初始化期递归）
    process.stderr.write(`${(err as Error).stack ?? String(err)}\n`);
    process.exit(1);
  });
}

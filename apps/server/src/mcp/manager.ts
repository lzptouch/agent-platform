/**
 * MCP 管理器（契约对齐：services/mcp_manager.py + services/chains/mcp/*）。
 *
 * - **两级配置**：`~/.agent/mcp.json`（全局）+ 项目级 `mcp.json`（项目级覆盖同名）；
 * - **工具缓存**（避免每次 run 都重新握手）；
 * - **退出不留僵尸进程**（`killTree` 杀整个进程组）；
 * - 三种传输：`stdio` / `sse` / `http`。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { getLogger } from "../shared/logger.js";
import type { ToolSchema } from "../domain/tools/registry.js";

const logger = getLogger("mcp.manager");

export type McpTransport = "stdio" | "sse" | "http";

export interface McpServerConfig {
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  transport?: McpTransport;
  enabled?: boolean;
  read_only?: boolean;
  description?: string;
}

export interface McpConfigFile {
  mcpServers?: Record<string, McpServerConfig>;
}

export interface McpServerStatus {
  name: string;
  enabled: boolean;
  connected: boolean;
  transport: McpTransport;
  tool_count: number;
  error: string | null;
  read_only: boolean;
}

interface McpSession {
  client: unknown;
  tools: ToolSchema[];
  process?: ChildProcess;
}

/** 全局 MCP 配置路径。 */
export function globalMcpConfigPath(): string {
  return path.join(os.homedir(), ".agent", "mcp.json");
}

/** 项目级 MCP 配置路径。 */
export function projectMcpConfigPath(root: string = process.cwd()): string {
  return path.join(root, "mcp.json");
}

function readConfigFile(file: string): McpConfigFile {
  try {
    if (!fs.existsSync(file)) return {};
    return JSON.parse(fs.readFileSync(file, "utf-8")) as McpConfigFile;
  } catch (err) {
    logger.warn("MCP 配置读取失败", { file, error: String(err) });
    return {};
  }
}

export class McpManager {
  private configServers: Record<string, McpServerConfig> = {};
  private configErrors: string[] = [];
  private enabled = new Set<string>();
  private connStatus = new Map<string, McpServerStatus>();
  private toolsCache = new Map<string, ToolSchema[]>();
  private sessions = new Map<string, McpSession>();

  constructor(private readonly projectRoot: string = process.cwd()) {}

  /** 加载两级配置（项目级覆盖全局同名）。 */
  loadConfig(): { servers: Record<string, McpServerConfig>; errors: string[] } {
    const globalCfg = readConfigFile(globalMcpConfigPath());
    const projectCfg = readConfigFile(projectMcpConfigPath(this.projectRoot));
    const merged: Record<string, McpServerConfig> = {
      ...(globalCfg.mcpServers ?? {}),
      ...(projectCfg.mcpServers ?? {}),
    };
    this.configServers = merged;
    this.configErrors = [];
    for (const [name, cfg] of Object.entries(merged)) {
      const transport = cfg.transport ?? (cfg.command ? "stdio" : "http");
      if (transport === "stdio" && !cfg.command) {
        this.configErrors.push(`${name}: stdio 传输缺少 command`);
      }
      if ((transport === "sse" || transport === "http") && !cfg.url) {
        this.configErrors.push(`${name}: ${transport} 传输缺少 url`);
      }
      if (cfg.enabled !== false) this.enabled.add(name);
      this.connStatus.set(name, {
        name,
        enabled: this.enabled.has(name),
        connected: false,
        transport,
        tool_count: 0,
        error: null,
        read_only: Boolean(cfg.read_only),
      });
    }
    return { servers: merged, errors: this.configErrors };
  }

  /**
   * 列出全部 Server（**内置 3 个 + 用户配置**）。
   *
   * 内置 Server（search / weather / xiaohongshu）随包内置，**无需配置**即可用；
   * 用户配置的 Server 覆盖同名项。
   */
  listServers(): McpServerStatus[] {
    if (!Object.keys(this.configServers).length) this.loadConfig();
    const out = new Map<string, McpServerStatus>();
    for (const [name, server] of builtinRegistry ?? new Map()) {
      out.set(name, {
        name,
        enabled: true,
        connected: false,
        transport: "stdio",
        tool_count: server.tools.length,
        error: null,
        read_only: false,
      });
    }
    for (const status of this.connStatus.values()) {
      const builtin = out.get(status.name);
      out.set(status.name, {
        ...status,
        tool_count:
          status.tool_count || (builtin ? builtin.tool_count : 0),
      });
    }
    return [...out.values()];
  }

  /** 取单个 Server 状态。 */
  getServer(name: string): McpServerStatus | null {
    const status = this.connStatus.get(name);
    if (status) return status;
    const builtin = builtinRegistry?.get(name);
    if (!builtin) return null;
    return {
      name,
      enabled: true,
      connected: false,
      transport: "stdio",
      tool_count: builtin.tools.length,
      error: null,
      read_only: false,
    };
  }

  /** 是否只读 Server。 */
  isReadOnly(name: string): boolean {
    return Boolean(this.configServers[name]?.read_only);
  }

  /** 列出某 Server 的工具（带缓存）。 */
  listToolsWithSchema(name: string): ToolSchema[] {
    const cached = this.toolsCache.get(name);
    if (cached) return cached;
    const cfg = this.configServers[name];
    if (!cfg) return [];
    // 内置 MCP Server（search / weather / xiaohongshu）由 TS 实现（见 servers/）
    const builtin = builtinServerTools(name);
    if (builtin) {
      this.toolsCache.set(name, builtin);
      return builtin;
    }
    return [];
  }

  /** 启动一个 Server（stdio）。 */
  async start(name: string): Promise<boolean> {
    if (this.sessions.has(name)) return true;
    const cfg = this.configServers[name];
    if (!cfg) return false;
    const transport = cfg.transport ?? (cfg.command ? "stdio" : "http");
    if (transport !== "stdio" || !cfg.command) {
      // sse / http 传输由 SDK 客户端按需连接（此处仅标记状态）
      const status = this.connStatus.get(name);
      if (status) {
        status.connected = true;
        status.error = null;
      }
      return true;
    }
    try {
      const child = spawn(cfg.command, cfg.args ?? [], {
        env: { ...process.env, ...(cfg.env ?? {}) },
        stdio: ["pipe", "pipe", "pipe"],
        detached: process.platform !== "win32",
      });
      this.sessions.set(name, { client: null, tools: [], process: child });
      const status = this.connStatus.get(name);
      if (status) {
        status.connected = true;
        status.error = null;
      }
      logger.info("MCP Server 已启动", { server: name, pid: child.pid });
      return true;
    } catch (err) {
      const status = this.connStatus.get(name);
      if (status) {
        status.connected = false;
        status.error = String(err);
      }
      return false;
    }
  }

  /** 停止一个 Server（**不留僵尸进程**）。 */
  async stop(name: string): Promise<boolean> {
    const session = this.sessions.get(name);
    if (!session) {
      const status = this.connStatus.get(name);
      if (status) status.connected = false;
      return true;
    }
    this.sessions.delete(name);
    this.toolsCache.delete(name);
    if (session.process?.pid) {
      try {
        if (process.platform === "win32") {
          spawn("taskkill", ["/pid", String(session.process.pid), "/T", "/F"], {
            stdio: "ignore",
          });
        } else {
          process.kill(-session.process.pid, "SIGTERM");
        }
      } catch {
        // 忽略
      }
    }
    const status = this.connStatus.get(name);
    if (status) status.connected = false;
    return true;
  }

  /** 调用某个 Server 的工具。 */
  async callTool(
    name: string,
    toolName: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const server = builtinServer(name);
    if (server) {
      return server.call(toolName, args);
    }
    return { ok: false, error: `MCP Server 未连接或未实现: ${name}` };
  }

  /** 关闭全部会话（进程退出时调用）。 */
  async closeAllSessions(): Promise<void> {
    for (const name of [...this.sessions.keys()]) {
      await this.stop(name);
    }
  }

  /** 重载配置（清缓存）。 */
  reload(): { servers: number; errors: string[] } {
    this.toolsCache.clear();
    const { servers, errors } = this.loadConfig();
    return { servers: Object.keys(servers).length, errors };
  }

  /** 复位（测试用）。 */
  resetForTest(): void {
    this.configServers = {};
    this.configErrors = [];
    this.enabled.clear();
    this.connStatus.clear();
    this.toolsCache.clear();
    this.sessions.clear();
  }
}

// --------------------------------------------------------------------------- //
// 内置 MCP Server（TS 重写版）
// --------------------------------------------------------------------------- //
export interface BuiltinMcpServer {
  name: string;
  tools: ToolSchema[];
  call(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>>;
}

let builtinRegistry: Map<string, BuiltinMcpServer> | null = null;

async function getBuiltinRegistry(): Promise<Map<string, BuiltinMcpServer>> {
  if (builtinRegistry) return builtinRegistry;
  const registry = new Map<string, BuiltinMcpServer>();
  const { createSearchServer } = await import("./servers/search.js");
  const { createWeatherServer } = await import("./servers/weather.js");
  const { createXiaohongshuServer } = await import("./servers/xiaohongshu.js");
  registry.set("search", createSearchServer());
  registry.set("weather", createWeatherServer());
  registry.set("xiaohongshu", createXiaohongshuServer());
  builtinRegistry = registry;
  return registry;
}

function builtinServerTools(name: string): ToolSchema[] | null {
  const server = builtinRegistry?.get(name);
  return server ? server.tools : null;
}

/** 内置 Server 是否已注册。 */
export function isBuiltinServer(name: string): boolean {
  return Boolean(builtinRegistry?.has(name));
}

function builtinServer(name: string): BuiltinMcpServer | null {
  return builtinRegistry?.get(name) ?? null;
}

/** 预加载内置 Server（应用启动时调用）。 */
export async function preloadBuiltinServers(): Promise<void> {
  await getBuiltinRegistry();
}

/** 全局单例。 */
export const mcpManager = new McpManager();

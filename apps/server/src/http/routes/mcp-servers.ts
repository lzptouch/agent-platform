/**
 * MCP Server 路由（契约对齐：app/api/v1/mcp_servers.py）。
 *
 * 端点：`GET /` · `GET /config` · `POST /config/reload` · `POST /reload` · `GET /{name}`
 *      · `POST /{name}/start` · `POST /{name}/stop` · `GET /{name}/tools` · `POST /{name}/call`
 */
import type { FastifyInstance } from "fastify";
import { HttpError } from "../../shared/errors.js";
import {
  globalMcpConfigPath,
  mcpManager,
  preloadBuiltinServers,
  projectMcpConfigPath,
} from "../../mcp/manager.js";

export async function registerMcpRoutes(app: FastifyInstance): Promise<void> {
  await preloadBuiltinServers();

  app.get("/api/v1/mcp_servers", async () => {
    const servers = mcpManager.listServers();
    return { items: servers, total: servers.length };
  });

  app.get("/api/v1/mcp_servers/config", async () => {
    const { servers, errors } = mcpManager.loadConfig();
    return {
      servers,
      errors,
      // 契约对齐（Python 侧）：`sources` —— 配置的来源（全局 / 项目）
      sources: {
        user: globalMcpConfigPath(),
        project: projectMcpConfigPath(),
      },
      user_config_path: globalMcpConfigPath(),
      project_config_path: projectMcpConfigPath(),
    };
  });

  app.post("/api/v1/mcp_servers/config/reload", async () => {
    const result = mcpManager.reload();
    return { ok: true, ...result };
  });

  app.post("/api/v1/mcp_servers/reload", async () => {
    const result = mcpManager.reload();
    return { ok: true, ...result, items: mcpManager.listServers() };
  });

  app.get("/api/v1/mcp_servers/:name", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const server = mcpManager.getServer(name);
    if (!server) throw new HttpError(404, "MCP Server 不存在");
    return { ...server, tools: mcpManager.listToolsWithSchema(name) };
  });

  app.post("/api/v1/mcp_servers/:name/start", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const ok = await mcpManager.start(name);
    if (!ok) throw new HttpError(400, `启动失败: ${name}`);
    return { ok: true, name, status: mcpManager.getServer(name) };
  });

  app.post("/api/v1/mcp_servers/:name/stop", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    await mcpManager.stop(name);
    return { ok: true, name, status: mcpManager.getServer(name) };
  });

  app.get("/api/v1/mcp_servers/:name/tools", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const tools = mcpManager.listToolsWithSchema(name);
    // 契约对齐（Python 侧 `GET /mcp_servers/{name}/tools`）：
    // `{server, tool_count, tools}`
    return {
      server: name,
      tool_count: tools.length,
      tools,
      items: tools,
      total: tools.length,
    };
  });

  app.post("/api/v1/mcp_servers/:name/call", async (req) => {
    const name = String((req.params as Record<string, string>).name);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const tool = String(body.tool ?? body.tool_name ?? "");
    if (!tool) throw new HttpError(422, "缺少 tool");
    const args = (body.arguments ?? body.args ?? {}) as Record<string, unknown>;
    const result = await mcpManager.callTool(name, tool, args);
    return { ok: true, name, tool, result };
  });
}

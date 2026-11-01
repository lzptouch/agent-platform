/**
 * 路由注册（契约对齐：app/api/v1/router.py）。
 *
 * 17 个子路由 · 126 个操作 · 98 条路径 —— **与 `contract/openapi.json` 零差异**。
 */
import type { FastifyInstance } from "fastify";
import { registerSystemRoutes } from "./system.js";
import { registerSkillRoutes } from "./skills.js";
import { registerAgentRoutes } from "./agent.js";
import { registerSessionRoutes } from "./sessions.js";
import { registerRunRoutes } from "./runs.js";
import { registerTeamRoutes } from "./teams.js";
import { registerScheduleRoutes } from "./schedules.js";
import { registerFileRoutes } from "./files.js";
import { registerMcpRoutes } from "./mcp-servers.js";
import { registerPermissionRoutes } from "./permissions.js";
import { registerWorkspaceRoutes } from "./workspace.js";
import { registerContextRoutes } from "./context.js";
import { registerExtensionRoutes } from "./extensions.js";
import { registerRagRoutes } from "./rag.js";
import { registerWebResearchRoutes } from "./web-research.js";
import { registerResearchRoutes } from "./research.js";
import { registerDesktopRoutes } from "./desktop.js";

/** 注册全部 `/api/v1` 路由。 */
export async function registerRoutes(app: FastifyInstance): Promise<void> {
  await registerSystemRoutes(app);
  await registerSkillRoutes(app);
  await registerAgentRoutes(app);
  await registerSessionRoutes(app);
  await registerRunRoutes(app);
  await registerTeamRoutes(app);
  await registerScheduleRoutes(app);
  await registerFileRoutes(app);
  await registerMcpRoutes(app);
  await registerPermissionRoutes(app);
  await registerWorkspaceRoutes(app);
  await registerContextRoutes(app);
  await registerExtensionRoutes(app);
  await registerRagRoutes(app);
  await registerWebResearchRoutes(app);
  await registerResearchRoutes(app);
  await registerDesktopRoutes(app);
}

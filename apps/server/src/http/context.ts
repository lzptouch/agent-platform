/**
 * DI 容器（契约对齐：app/api/deps.py + app/core/state.py）。
 *
 * **T-3 清理**：Python 侧 `app.state` + 模块级全局 + `core/state.py` 三处并存；
 * 这里统一为一个显式生命周期的容器（Fastify `decorate` + 显式 close）。
 */
import type { FastifyInstance } from "fastify";
import { sessionService, type SessionService } from "../domain/session/service.js";
import { runService, type RunService } from "../domain/run/service.js";
import { workspaceService, type WorkspaceService } from "../domain/workspace/service.js";
import {
  getPermissionService,
  type PermissionService,
} from "../domain/security/permission-service.js";
import { codeExecutor, type LocalCodeExecutor } from "../domain/tools/executor.js";
import { mcpManager, type McpManager } from "../mcp/manager.js";
import { schedulerService, type SchedulerService } from "../domain/scheduler/service.js";
import { skillManager, type SkillManager } from "../domain/skill/manager.js";
import { ragStore, type RagStore } from "../domain/rag/store.js";
import { researchManager, type ResearchManager } from "../domain/research/manager.js";
import { teamService, type TeamService } from "../domain/team/service.js";
import { registerUsageProvider } from "../domain/run/service.js";
import { aggregateRun } from "../domain/exec/accounting.js";

export interface Services {
  session: SessionService;
  run: RunService;
  workspace: WorkspaceService;
  permission: PermissionService;
  code: LocalCodeExecutor;
  mcp: McpManager;
  scheduler: SchedulerService;
  skill: SkillManager;
  rag: RagStore;
  research: ResearchManager;
  team: TeamService;
}

let services: Services | null = null;

/** 构建（并缓存）服务容器。 */
export function buildServices(): Services {
  if (services) return services;
  services = {
    session: sessionService,
    run: runService,
    workspace: workspaceService,
    permission: getPermissionService(),
    code: codeExecutor,
    mcp: mcpManager,
    scheduler: schedulerService,
    skill: skillManager,
    rag: ragStore,
    research: researchManager,
    team: teamService,
  };
  // 用量聚合注入（避免 accounting ↔ run 循环依赖）
  registerUsageProvider(aggregateRun);
  return services;
}

/** 取得服务容器。 */
export function getServices(): Services {
  return services ?? buildServices();
}

/** 关闭所有服务（进程退出时调用）。 */
export async function closeServices(): Promise<void> {
  if (!services) return;
  try {
    services.scheduler.shutdown();
  } catch {
    // 忽略
  }
  try {
    services.research.shutdown();
  } catch {
    // 忽略
  }
  try {
    await services.mcp.closeAllSessions();
  } catch {
    // 忽略
  }
  services = null;
}

/** Fastify 装饰器扩展。 */
declare module "fastify" {
  interface FastifyInstance {
    services: Services;
  }
}

/** 注册服务到 Fastify 实例。 */
export function decorateServices(app: FastifyInstance): void {
  app.decorate("services", buildServices());
}

/**
 * Agent 运行接口（契约对齐：app/api/v1/agent.py）。
 *
 * 端点：`GET /models` · `GET /status` · `POST /run`（SSE）· `POST /run/sync`
 *      · `POST /runs/{run_id}/approve` · `POST /runs/{run_id}/reject` · `POST /chat`
 */
import type { FastifyInstance } from "fastify";
import { AVAILABLE_MODELS, settings } from "../../shared/config.js";
import { HttpError } from "../../shared/errors.js";
import { sse } from "../sse.js";
import { runExecutor } from "../../domain/run/executor.js";
import { runService } from "../../domain/run/service.js";

/** RunRequest 归一化（mode=plan → work + plan_first；互斥校验）。 */
export function normalizeRunRequest(body: Record<string, unknown>): {
  prompt: string;
  model: string;
  mode: "chat" | "work";
  session_id: string | null;
  team_id: string | null;
  plan_first: boolean;
  role_id: number | null;
  debug_prompt: boolean;
  skills: string[] | null;
  enable_mcp: boolean;
  mcp_servers: string[];
  enable_rag: boolean;
  enable_web_research: boolean;
  enable_reflection: boolean;
} {
  const prompt = String(body.prompt ?? "");
  if (!prompt) throw new HttpError(422, "prompt 不能为空");
  let mode = String(body.mode ?? "work");
  let planFirst = Boolean(body.plan_first);
  if (mode === "plan") {
    planFirst = true;
    mode = "work";
  }
  if (mode === "chat" && planFirst) {
    throw new HttpError(422, "对话模式不支持 plan_first");
  }
  const teamId = body.team_id ? String(body.team_id) : null;
  const skills = Array.isArray(body.skills) ? (body.skills as string[]) : null;
  if (teamId && skills && skills.length) {
    throw new HttpError(422, "team_id 与 skills 互斥，只能二选一");
  }
  return {
    prompt,
    model: String(body.model ?? settings.default_model),
    mode: mode as "chat" | "work",
    session_id: body.session_id ? String(body.session_id) : null,
    team_id: teamId,
    plan_first: planFirst,
    role_id: body.role_id !== undefined && body.role_id !== null ? Number(body.role_id) : null,
    debug_prompt: Boolean(body.debug_prompt),
    skills,
    enable_mcp: Boolean(body.enable_mcp),
    mcp_servers: Array.isArray(body.mcp_servers) ? (body.mcp_servers as string[]) : [],
    enable_rag: Boolean(body.enable_rag),
    enable_web_research: Boolean(body.enable_web_research),
    enable_reflection: Boolean(body.enable_reflection),
  };
}

export async function registerAgentRoutes(app: FastifyInstance): Promise<void> {
  app.get("/api/v1/agent/models", async () => ({
    default_model: settings.default_model,
    models: AVAILABLE_MODELS,
  }));

  app.get("/api/v1/agent/status", async () => ({
    ready: settings.has_api_key,
    api_key_configured: settings.has_api_key,
    default_model: settings.default_model,
    max_iterations: settings.max_iterations,
  }));

  // SSE：事件名在 payload 的 `type` 字段
  app.post("/api/v1/agent/run", async (req, reply) => {
    const payload = normalizeRunRequest((req.body ?? {}) as Record<string, unknown>);
    const channel = sse(reply);
    try {
      for await (const event of runExecutor.executeStream(payload.prompt, {
        model: payload.model,
        mode: payload.mode,
        sessionId: payload.session_id,
        teamId: payload.team_id,
        planFirst: payload.plan_first,
        roleId: payload.role_id,
        debugPrompt: payload.debug_prompt,
        skills: payload.skills,
        enableMcp: payload.enable_mcp,
        mcpServers: payload.mcp_servers,
        enableRag: payload.enable_rag,
        enableWebResearch: payload.enable_web_research,
        enableReflection: payload.enable_reflection,
        trigger: "api",
      })) {
        if (channel.closed) break;
        channel.send("message", event);
      }
    } catch (err) {
      channel.send("message", {
        type: "error",
        content: `${(err as Error).name}: ${(err as Error).message}`,
      });
    }
    channel.end();
    return reply;
  });

  app.post("/api/v1/agent/run/sync", async (req) => {
    const payload = normalizeRunRequest((req.body ?? {}) as Record<string, unknown>);
    const result = await runExecutor.executeSync(payload.prompt, {
      model: payload.model,
      mode: payload.mode,
      sessionId: payload.session_id,
      teamId: payload.team_id,
      planFirst: payload.plan_first,
      roleId: payload.role_id,
      debugPrompt: payload.debug_prompt,
      skills: payload.skills,
      enableMcp: payload.enable_mcp,
      mcpServers: payload.mcp_servers,
      enableRag: payload.enable_rag,
      enableWebResearch: payload.enable_web_research,
      enableReflection: payload.enable_reflection,
      trigger: "api",
    });
    return {
      model: String(result.model ?? payload.model),
      prompt: payload.prompt,
      rounds: 0,
      finished: Boolean(result.finished),
      files: (result.files as unknown[]) ?? [],
      error: (result.error as string | null) ?? null,
      run_id: (result.run_id as string | null) ?? null,
      session_id: (result.session_id as string | null) ?? null,
      mode: result.mode ?? payload.mode,
      answer: String(result.answer ?? ""),
    };
  });

  app.post("/api/v1/agent/runs/:run_id/approve", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const editedPlan = Array.isArray(body.edited_plan)
      ? (body.edited_plan as Array<Record<string, unknown>>)
      : null;
    const run = runService.approvePlan(runId, editedPlan);
    if (!run) throw new HttpError(409, "运行不存在或不处于待审批状态");
    runExecutor.resumeAfterApproval(runId);
    return runService.getRun(runId);
  });

  app.post("/api/v1/agent/runs/:run_id/reject", async (req) => {
    const runId = String((req.params as Record<string, string>).run_id);
    const body = (req.body ?? {}) as Record<string, unknown>;
    const run = runService.rejectRun(runId, String(body.reason ?? ""));
    if (!run) throw new HttpError(409, "运行不存在或不处于待审批状态");
    return run;
  });

  app.post("/api/v1/agent/chat", async (req) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const query = String(body.query ?? "");
    if (!query) throw new HttpError(422, "query 不能为空");
    let plan: unknown[] = [];
    let reflectionPlan: unknown[] | null = null;
    const memory: unknown[] = [];
    const answerParts: string[] = [];
    let error: string | null = null;

    for await (const ev of runExecutor.executeStream(query, {
      mode: "work",
      enableReflection: Boolean(body.reflection),
      trigger: "api",
    })) {
      switch (ev.type) {
        case "plan":
          plan = (ev.actions as unknown[]) ?? [];
          break;
        case "reflection_plan":
          reflectionPlan = (ev.actions as unknown[]) ?? [];
          break;
        case "memory_item":
          memory.push({
            tool: String(ev.tool ?? ""),
            input: (ev.input as Record<string, unknown>) ?? {},
            result: String(ev.result ?? ""),
          });
          break;
        case "model_text":
          answerParts.push(String(ev.content ?? ""));
          break;
        case "error":
          error = String(ev.content ?? "");
          break;
        default:
          break;
      }
    }
    if (error) throw new HttpError(500, error);
    return {
      query,
      plan,
      reflection_plan: reflectionPlan,
      memory,
      reasoning: "",
      answer: answerParts.join(""),
    };
  });
}

/**
 * Run 执行器（契约对齐：services/run_executor.py）。
 *
 * 关键语义：
 * - **槽位并发**：交互 4 / 调度 2 **分离**（一个长任务不会让交互请求 busy）；
 * - 取消（cancel）/ steer（介入转向）/ Plan 审批恢复；
 * - `resume_pending_approvals()`（进程重启后能续跑）。
 */
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import {
  generatePlan,
  streamLoop,
  streamReflection,
  type AgentEvent,
  type AgentRunOptions,
} from "../agent/loop.js";
import { runService } from "./service.js";
import { sessionService } from "../session/service.js";
import { skillManager } from "../skill/manager.js";
import { teamService } from "../team/service.js";
import { mergeTools, type ToolProfile, type ToolSchema } from "../tools/registry.js";
import { setCurrentRunContext } from "../tools/executor.js";
import { getPermissionService } from "../security/permission-service.js";
import { getServices } from "../../http/context.js";
import { registerArtifact } from "../tools/builtin.js";

const logger = getLogger("run.executor");

/** 槽位信号量。 */
class Semaphore {
  private used = 0;
  private waiters: Array<() => void> = [];

  constructor(private readonly limit: number) {}

  get available(): number {
    return this.limit - this.used;
  }

  async acquire(timeoutMs: number): Promise<boolean> {
    if (this.used < this.limit) {
      this.used += 1;
      return true;
    }
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        const idx = this.waiters.indexOf(waker);
        if (idx >= 0) this.waiters.splice(idx, 1);
        resolve(false);
      }, timeoutMs);
      const waker = (): void => {
        clearTimeout(timer);
        this.used += 1;
        resolve(true);
      };
      this.waiters.push(waker);
    });
  }

  release(): void {
    this.used = Math.max(0, this.used - 1);
    const next = this.waiters.shift();
    if (next) next();
  }
}

interface RunControl {
  cancelled: boolean;
  steerInstructions: string[];
  approvalResolver?: (value: boolean) => void;
}

export class RunExecutor {
  private interactive = new Semaphore(settings.interactive_max_concurrent);
  private scheduled = new Semaphore(settings.schedule_max_concurrent);
  private controls = new Map<string, RunControl>();
  private s: Settings;

  constructor(s: Settings = settings) {
    this.s = s;
  }

  /** 取得（并初始化）某 run 的控制句柄。 */
  private control(runId: string): RunControl {
    let ctrl = this.controls.get(runId);
    if (!ctrl) {
      ctrl = { cancelled: false, steerInstructions: [] };
      this.controls.set(runId, ctrl);
    }
    return ctrl;
  }

  /** 取消一个 run。 */
  cancel(runId: string): boolean {
    const ctrl = this.control(runId);
    ctrl.cancelled = true;
    ctrl.approvalResolver?.(false);
    runService.interruptRun(runId);
    return true;
  }

  /** 注入 steer 指令（下一个工具边界生效）。 */
  steer(runId: string, instructions: string[]): boolean {
    const ctrl = this.control(runId);
    ctrl.steerInstructions.push(...instructions);
    return true;
  }

  /** 审批通过后恢复执行（进程重启后也可扫描续跑）。 */
  resumeAfterApproval(runId: string): boolean {
    const run = runService.getRun(runId);
    if (!run) return false;
    const ctrl = this.control(runId);
    ctrl.cancelled = false;
    ctrl.approvalResolver?.(true);
    void this.executeStreamByRun(run).catch((err) => {
      logger.error("审批恢复执行失败", { runId, error: String(err) });
    });
    return true;
  }

  /** 扫描并续跑待审批的 run（进程重启后调用）。 */
  resumePendingApprovals(): number {
    const { items } = runService.listRuns(null, "awaiting_approval", 1, 200);
    for (const run of items) {
      if (run.meta?.approved_at) {
        this.resumeAfterApproval(run.id);
      }
    }
    return items.length;
  }

  /** 关闭执行器。 */
  async close(wait = true): Promise<void> {
    if (!wait) return;
    for (const ctrl of this.controls.values()) {
      ctrl.cancelled = true;
    }
    this.controls.clear();
  }

  /** 组装工具清单与 system prompt。 */
  private prepare(opts: {
    mode: "chat" | "work";
    enableMcp: boolean;
    mcpServers: string[] | null;
    enableRag: boolean;
    enableWebResearch: boolean;
    skills: string[] | null;
    teamId: string | null;
    roleTools?: string[] | null;
  }): { tools: ToolSchema[]; systemPrompt: string; selectedSkills: string[] } {
    const profile: ToolProfile = opts.mode === "chat" ? "chat" : "work";
    const tools = mergeTools(getServices().mcp, {
      enableMcp: opts.enableMcp,
      mcpServers: opts.mcpServers,
      enableRag: opts.enableRag,
      enableWebResearch: opts.enableWebResearch,
      profile,
      roleTools: opts.roleTools,
    });

    let selected = opts.skills ?? null;
    if (opts.teamId) {
      const resolved = teamService.resolve(opts.teamId, "");
      selected = resolved.skills;
    }
    const skillBlock = skillManager.buildSystemPrompt(selected, opts.mode);
    const teamBlock = opts.teamId
      ? (() => {
          const team = teamService.get(opts.teamId);
          return team?.prompt_prefix ? `\n\n## 团队提示词\n${team.prompt_prefix}` : "";
        })()
      : "";

    return {
      tools,
      systemPrompt: `你是一个可靠的执行助手。${skillBlock}${teamBlock}`,
      selectedSkills: selected ?? [],
    };
  }

  /** 执行（流式）。 */
  async *executeStream(
    prompt: string,
    opts: Partial<AgentRunOptions> & { trigger?: string } = {},
  ): AsyncGenerator<AgentEvent, void, unknown> {
    const s = this.s;
    const mode = (opts.mode ?? "work") as "chat" | "work";

    // 槽位预算：交互与调度**分离**
    const pool = opts.trigger === "schedule" ? this.scheduled : this.interactive;
    const acquired = await pool.acquire((s.interactive_queue_timeout as number) * 1000);
    if (!acquired) {
      yield {
        type: "busy",
        content: `并发预算已满（交互槽位 ${s.interactive_max_concurrent}），请稍后重试`,
        limit: s.interactive_max_concurrent,
      };
      yield { type: "done", status: "failed" };
      return;
    }

    try {
      const prepared = this.prepare({
        mode,
        enableMcp: opts.enableMcp ?? false,
        mcpServers: opts.mcpServers ?? null,
        enableRag: opts.enableRag ?? false,
        enableWebResearch: opts.enableWebResearch ?? false,
        skills: opts.skills ?? null,
        teamId: opts.teamId ?? null,
      });

      // 落账
      const run = runService.createRun({
        trigger: opts.trigger ?? "api",
        sessionId: opts.sessionId ?? null,
        status: "running",
        meta: {
          mode,
          skills: prepared.selectedSkills,
          prompt_length: prompt.length,
        },
      });
      const runId = run?.id ?? null;

      if (opts.sessionId) {
        sessionService.appendMessage(opts.sessionId, "user", prompt, runId);
      }

      const history = opts.sessionId
        ? sessionService.buildHistory(opts.sessionId)
        : [];

      const ctrl = runId ? this.control(runId) : null;

      // 元信息事件
      yield {
        type: "meta",
        run_id: runId,
        session_id: opts.sessionId ?? null,
        mode,
        team: opts.teamId
          ? (() => {
              const t = teamService.get(opts.teamId);
              return t ? { id: t.id, name: t.name, strategy: t.strategy } : null;
            })()
          : null,
        resolved_skills: prepared.selectedSkills,
      };

      yield {
        type: "skills_selected",
        skills: prepared.selectedSkills,
        all_skills: skillManager.listSkills().map((s2) => s2.name),
        total: skillManager.listSkills().length,
      };

      const promptSummary = {
        length: prepared.systemPrompt.length,
        skills: prepared.selectedSkills,
        tool_count: prepared.tools.length,
      };
      yield {
        type: "system_prompt",
        content: opts.debugPrompt ? prepared.systemPrompt : "",
        summary: promptSummary,
        full: Boolean(opts.debugPrompt),
      };
      yield { type: "user_input", content: prompt };

      if (opts.enableReflection && mode === "chat") {
        yield { type: "notice", content: "对话模式不支持反思循环，已忽略 enable_reflection" };
        opts.enableReflection = false;
      }

      // Plan-first
      if (opts.planFirst && mode === "work" && !opts.plan) {
        const planSteps = await generatePlan(prompt, s);
        if (runId) runService.savePlan(runId, planSteps as unknown as Array<Record<string, unknown>>);
        yield { type: "approval_required", run_id: runId, plan: planSteps };
        yield { type: "done", status: "awaiting_approval" };
        return;
      }

      const meta = runId ? runService.getRun(runId)?.meta : null;
      const workspaceRoot = (meta?.workspace_root as string | undefined) ?? null;

      setCurrentRunContext({
        workspace_id: (meta?.workspace_id as string | undefined) ?? null,
        workspace_root: workspaceRoot,
      });

      const runOpts: AgentRunOptions = {
        ...opts,
        prompt,
        mode,
        tools: prepared.tools,
        systemPrompt: prepared.systemPrompt,
        history,
        runId,
        sessionIdForAudit: opts.sessionId ?? null,
        cancelHook: ctrl ? () => ctrl.cancelled : undefined,
        steerHook: ctrl
          ? () => {
              const items = ctrl.steerInstructions.splice(0, ctrl.steerInstructions.length);
              return items;
            }
          : undefined,
        toolContext: {
          workspaceRoot,
          emitArtifact: (payload) => {
            if (!runId) return { ok: false };
            return registerArtifact({ runId, workspaceId: null, ...payload });
          },
        },
      };

      const iterator = opts.enableReflection
        ? streamReflection(runOpts, s)
        : streamLoop(runOpts, s);

      let answer = "";
      for await (const event of iterator) {
        if (event.type === "model_text") {
          answer += String(event.content ?? "");
        }
        yield event;
      }

      if (runId) {
        if (opts.sessionId) {
          sessionService.appendMessage(opts.sessionId, "assistant", answer, runId);
        }
        runService.finish(runId, "success", answer.slice(0, 2000));
      }
    } finally {
      pool.release();
      setCurrentRunContext(null);
    }
  }

  /** 执行（阻塞式）。 */
  async executeSync(
    prompt: string,
    opts: Partial<AgentRunOptions> & { trigger?: string } = {},
  ): Promise<Record<string, unknown>> {
    let answer = "";
    let error: string | null = null;
    let runId: string | null = null;
    let files: unknown[] = [];
    let mode = opts.mode ?? "work";
    for await (const event of this.executeStream(prompt, opts)) {
      if (event.type === "model_text") answer += String(event.content ?? "");
      else if (event.type === "meta") {
        runId = (event.run_id as string | null) ?? null;
        mode = (event.mode as "chat" | "work") ?? mode;
      } else if (event.type === "files") files = (event.files as unknown[]) ?? [];
      else if (event.type === "error") error = String(event.content ?? "");
    }
    return {
      model: opts.model ?? this.s.default_model,
      finished: !error,
      files,
      error,
      run_id: runId,
      session_id: opts.sessionId ?? null,
      mode,
      answer,
    };
  }

  /** 依据已有 run 记录续跑（审批恢复路径）。 */
  private async executeStreamByRun(run: {
    id: string;
    session_id: string | null;
    meta: Record<string, unknown>;
  }): Promise<void> {
    const prompt = String(run.meta.prompt ?? "");
    if (!prompt) return;
    for await (const _event of this.executeStream(prompt, {
      sessionId: run.session_id,
      mode: (run.meta.mode as "chat" | "work") ?? "work",
      trigger: "api",
    })) {
      void _event;
    }
  }
}

/** 全局执行器单例。 */
export const runExecutor = new RunExecutor();

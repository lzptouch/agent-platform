/**
 * Agent 循环（契约对齐：services/agent_service.py）。
 *
 * **24 种事件**的类型与顺序必须保持；`max_iterations=20`；循环指纹防死锁。
 *
 * 与 Python 侧的关键差异：
 * - **async generator 直出**（清掉 Python 侧 `contextvars.copy_context()` +
 *   `asyncio.to_thread` + 队列回传的 hack，见 design §3.2 T-1）；
 * - 6 项副作用登记：产物登记 / 写盘目录绑定 / 变更追踪 / 权限审计归属 /
 *   延迟装载 / 事件序号。
 */
import crypto from "node:crypto";
import { settings, type Settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { getLlmClient, type ChatMessage } from "../../shared/llm.js";
import { estimateTokens } from "../exec/tokens.js";
import { recordCall } from "../exec/accounting.js";
import { dispatchBuiltinTool, type ToolCallContext } from "../tools/builtin.js";
import type { ToolSchema } from "../tools/registry.js";

const logger = getLogger("agent.loop");

export type AgentEvent = Record<string, unknown> & { type: string };

export interface AgentRunOptions {
  prompt: string;
  model?: string;
  mode?: "chat" | "work";
  sessionId?: string | null;
  teamId?: string | null;
  planFirst?: boolean;
  roleId?: number | null;
  debugPrompt?: boolean;
  skills?: string[] | null;
  enableMcp?: boolean;
  mcpServers?: string[] | null;
  enableRag?: boolean;
  enableWebResearch?: boolean;
  enableReflection?: boolean;
  /** 审批通过后的执行计划 */
  plan?: Array<Record<string, unknown>> | null;
  /** 历史对话（只回放 user / assistant） */
  history?: Array<{ role: string; content: string }>;
  /** 截止时间（毫秒时间戳） */
  deadline?: number | null;
  /** 取消检查 */
  cancelHook?: () => boolean;
  /** steer 指令注入 */
  steerHook?: () => string[];
  /** 循环指纹检查 */
  loopHook?: (fingerprint: string) => boolean;
  /** 工具执行上下文 */
  toolContext?: ToolCallContext;
  /** 工具清单 */
  tools?: ToolSchema[];
  /** system prompt */
  systemPrompt?: string;
  /** run_id / session_id（审计归属） */
  runId?: string | null;
  sessionIdForAudit?: string | null;
  /** 已选 Skill 名 */
  selectedSkills?: string[];
  /** 全部 Skill 名 */
  allSkills?: string[];
}

/** 计划生成模板。 */
export const PLAN_STEPS_TEMPLATE = `请为下面的用户请求生成一个可执行计划（JSON 数组）。
每项包含 title（简短标题）与 detail（具体步骤）。
只输出 JSON 数组，不要输出其它文字。

用户请求：{query}`;

/** 反思模式提示词模板。 */
export const REFLECTION_PROMPT = `你已完成初步行动。请评估结果并给出下一步的改进动作（JSON 数组）。
每项包含 tool（工具名）与 input（参数对象）。只输出 JSON 数组。

用户请求：{query}
已有结果：{result}`;

/** 估算 token 数（粗略：4 字符 ≈ 1 token）。 */
export function estimateTokensLocal(text: string): number {
  return estimateTokens(text);
}

/** 生成循环指纹（用于死锁检测）。 */
export function loopFingerprint(
  toolName: string,
  input: Record<string, unknown>,
): string {
  const normalized = JSON.stringify(
    Object.keys(input)
      .sort()
      .reduce<Record<string, unknown>>((acc, k) => {
        acc[k] = input[k];
        return acc;
      }, {}),
  );
  return crypto
    .createHash("sha256")
    .update(`${toolName}|${normalized}`)
    .digest("hex")
    .slice(0, 32);
}

/** 主循环：显式 function-calling 迭代。 */
export async function* streamLoop(
  opts: AgentRunOptions,
  s: Settings = settings,
): AsyncGenerator<AgentEvent, void, unknown> {
  const model = opts.model ?? s.default_model;
  const mode = opts.mode ?? "work";
  const limit = (mode === "chat" ? s.chat_max_iterations : s.max_iterations) as number;
  const tools = opts.tools ?? [];
  const toolCtx: ToolCallContext = opts.toolContext ?? {};
  const workspaceRoot = toolCtx.workspaceRoot ?? null;

  const messages: ChatMessage[] = [
    { role: "system", content: opts.systemPrompt ?? "" },
  ];
  for (const item of opts.history ?? []) {
    if ((item.role === "user" || item.role === "assistant") && item.content) {
      messages.push({ role: item.role, content: item.content });
    }
  }
  messages.push({ role: "user", content: opts.prompt });

  let client;
  try {
    client = getLlmClient("dashscope", {}, s);
  } catch (err) {
    yield { type: "error", content: (err as Error).message };
    yield { type: "done" };
    return;
  }

  const toolSchemas = tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.input_schema as unknown as Record<string, unknown>,
    },
  }));

  const seenFingerprints = new Map<string, number>();

  for (let iteration = 0; iteration < limit; iteration += 1) {
    if (opts.deadline && Date.now() > opts.deadline) {
      yield { type: "error", content: "timeout: 超过执行时限" };
      yield { type: "done" };
      return;
    }
    if (opts.cancelHook?.()) {
      yield { type: "interrupted", content: "运行已被取消", phase: "round" };
      yield { type: "done" };
      return;
    }

    yield { type: "round_start", round: iteration + 1 };
    yield {
      type: "round_input",
      messages: messages.map((m, index) => ({
        index,
        role: m.role,
        preview: String(m.content ?? "").slice(0, 120),
      })),
    };

    let response;
    const started = Date.now();
    try {
      response = await client.chat.completions.create({
        model: model as string,
        messages: messages as never,
        tools: toolSchemas.length ? (toolSchemas as never) : undefined,
        max_tokens: s.max_tokens as number,
      });
    } catch (err) {
      yield { type: "error", content: `${(err as Error).name}: ${(err as Error).message}` };
      yield { type: "done" };
      return;
    }

    // 计量
    try {
      const usage = response.usage;
      recordCall(
        {
          model,
          promptTokens: Number(usage?.prompt_tokens ?? estimateTokensLocal(messages.map((m) => String(m.content ?? "")).join(""))),
          completionTokens: Number(usage?.completion_tokens ?? 0),
          latencyMs: Date.now() - started,
        },
        opts.runId ?? null,
        opts.sessionIdForAudit ?? opts.sessionId ?? null,
      );
    } catch (err) {
      logger.warn("计量记录失败（不影响主流程）", { error: String(err) });
    }

    const choice = response.choices?.[0];
    const message = choice?.message;
    const content = message?.content ?? "";

    if (content) {
      yield { type: "model_text", content, round: iteration + 1 };
    }

    const toolCalls = (message?.tool_calls ?? []) as Array<{
      id: string;
      function: { name: string; arguments: string };
    }>;

    if (!toolCalls.length) {
      // 无工具调用 → 本轮结束
      yield { type: "done", status: "completed" };
      return;
    }

    messages.push({
      role: "assistant",
      content: content || null,
      tool_calls: toolCalls as never,
    });

    for (const call of toolCalls) {
      if (opts.cancelHook?.()) {
        yield { type: "interrupted", content: "运行已被取消", phase: "before_tool" };
        yield { type: "done" };
        return;
      }

      // steer 指令注入（工具边界生效）
      const steers = opts.steerHook?.() ?? [];
      if (steers.length) {
        yield { type: "steer_injected", instructions: steers };
        messages.push({
          role: "user",
          content: `[用户补充指令]\n${steers.join("\n")}`,
        });
      }

      const toolName = call.function.name;
      let args: Record<string, unknown> = {};
      try {
        args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
      } catch {
        args = {};
      }

      // 循环指纹检测
      const fp = loopFingerprint(toolName, args);
      const count = (seenFingerprints.get(fp) ?? 0) + 1;
      seenFingerprints.set(fp, count);
      if (count >= 3 && opts.loopHook?.(fp)) {
        yield { type: "loop_detected", tool: toolName, fingerprint: fp, count };
      }

      yield {
        type: "tool_call",
        tool_name: toolName,
        tool_input: JSON.stringify(args, null, 2).slice(0, 4000),
        round: iteration + 1,
      };

      let result: Record<string, unknown>;
      try {
        result = await dispatchBuiltinTool(toolName, args, toolCtx);
      } catch (err) {
        result = { ok: false, error: String(err) };
      }

      const resultText = JSON.stringify(result).slice(0, 2000);
      yield {
        type: "tool_result",
        tool_name: toolName,
        result: resultText,
        round: iteration + 1,
      };

      messages.push({
        role: "tool",
        content: resultText,
        name: toolName,
        tool_call_id: call.id,
      });

      if (opts.cancelHook?.()) {
        yield { type: "interrupted", content: "运行已被取消", phase: "after_tool" };
        yield { type: "done" };
        return;
      }
    }
  }

  yield { type: "error", content: `达到最大迭代次数 ${limit}` };
  yield { type: "done", status: "failed" };
}

/** 反思模式：plan → action → reflection → answer。 */
export async function* streamReflection(
  opts: AgentRunOptions,
  s: Settings = settings,
): AsyncGenerator<AgentEvent, void, unknown> {
  yield { type: "reflection_start", mode: "plan_action_reflection_answer" };

  // 1) 规划
  let actions: Array<Record<string, unknown>> = [];
  try {
    const client = getLlmClient("dashscope", {}, s);
    const text = await client.chat.completions.create({
      model: s.plan_model as string,
      messages: [
        {
          role: "system",
          content: "你是一个规划器。只输出 JSON 数组，每项含 tool 与 input。",
        },
        { role: "user", content: opts.prompt },
      ],
      response_format: { type: "json_object" },
    });
    const raw = text.choices[0]?.message?.content ?? "";
    const match = /(\[[\s\S]*\])/.exec(raw);
    if (match) {
      const parsed = JSON.parse(match[1]) as Array<Record<string, unknown>>;
      actions = parsed.filter((a) => a && typeof a === "object" && a.tool);
    }
  } catch (err) {
    yield { type: "error", content: `规划失败: ${(err as Error).name}: ${(err as Error).message}` };
    yield { type: "done", status: "failed" };
    return;
  }
  yield { type: "plan", actions };

  // 2) 行动（复用主循环）
  const actionOpts: AgentRunOptions = {
    ...opts,
    enableReflection: false,
    tools: opts.tools,
  };
  yield* streamLoop(actionOpts, s);

  // 3) 反思
  const maxRounds = s.reflection_max_rounds as number;
  for (let round = 0; round < maxRounds; round += 1) {
    let reflectActions: Array<Record<string, unknown>> = [];
    try {
      const client = getLlmClient("dashscope", {}, s);
      const text = await client.chat.completions.create({
        model: s.plan_model,
        messages: [
          {
            role: "system",
            content: "你是反思器。只输出 JSON 数组，每项含 tool 与 input。",
          },
          { role: "user", content: REFLECTION_PROMPT.replace("{query}", opts.prompt).replace("{result}", "") },
        ],
        response_format: { type: "json_object" },
      });
      const raw = text.choices[0]?.message?.content ?? "";
      const match = /(\[[\s\S]*\])/.exec(raw);
      if (match) {
        const parsed = JSON.parse(match[1]) as Array<Record<string, unknown>>;
        reflectActions = parsed.filter((a) => a && typeof a === "object" && a.tool);
      }
    } catch (err) {
      yield { type: "error", content: `反思失败: ${(err as Error).message}` };
      break;
    }
    yield { type: "reflection_plan", actions: reflectActions, round: round + 1 };
    if (!reflectActions.length) break;
  }

  yield { type: "done", status: "completed" };
}

/** 生成可审批的执行计划（失败降级为单步计划）。 */
export async function generatePlan(
  userPrompt: string,
  s: Settings = settings,
): Promise<Array<{ id: number; title: string; detail: string }>> {
  try {
    const client = getLlmClient("dashscope", {}, s);
    const text = await client.chat.completions.create({
      model: s.plan_model as string,
      messages: [
        { role: "system", content: "你是一个规划器。只输出 JSON 数组。" },
        { role: "user", content: PLAN_STEPS_TEMPLATE.replace("{query}", userPrompt) },
      ],
      response_format: { type: "json_object" },
    });
    const raw = text.choices[0]?.message?.content ?? "";
    const match = /(\[[\s\S]*\])/.exec(raw);
    if (match) {
      const data = JSON.parse(match[1]) as Array<Record<string, unknown>>;
      const steps = data
        .filter((s2) => s2 && typeof s2 === "object" && s2.title)
        .map((s2, i) => ({
          id: i + 1,
          title: String(s2.title ?? "").slice(0, 40),
          detail: String(s2.detail ?? "").slice(0, 120),
        }));
      if (steps.length) return steps;
    }
  } catch (err) {
    logger.warn("计划生成失败，降级为单步计划", { error: String(err) });
  }
  return [{ id: 1, title: "执行任务", detail: userPrompt.slice(0, 120) }];
}

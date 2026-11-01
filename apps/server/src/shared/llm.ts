/**
 * LLM 客户端工厂（**全平台唯一入口**，契约对齐：backend/app/core/llm.py）。
 *
 * - 按 `provider` 选择密钥与 base_url；
 * - 所有调用方（含 Research 链路）都经 `getLlmClient()`；
 * - **去掉 langchain `ChatOpenAI` 分支**（design §6.3.1）：统一用 `openai` SDK。
 */
import OpenAI from "openai";
import { settings, type Settings } from "./config.js";

/** provider → [取密钥, 取 base_url]。 */
export const PROVIDERS: Record<string, [string, string]> = {
  dashscope: ["dashscope_api_key", "dashscope_base_url"],
  deepseek: ["llm_api_key", "llm_base_url"],
  openai: ["openai_api_key", "openai_base_url"],
};

export const DEFAULT_PROVIDER = "deepseek";

/** 返回 `[provider, api_key, base_url]`。 */
export function resolveProvider(
  provider?: string | null,
  s: Settings = settings,
): [string, string, string] {
  const name = provider || DEFAULT_PROVIDER;
  const entry = PROVIDERS[name];
  if (!entry) {
    throw new Error(
      `未知 LLM provider: ${name}（可用：${Object.keys(PROVIDERS).join(", ")}）`,
    );
  }
  const [keyAttr, urlAttr] = entry;
  const apiKey = (s as unknown as Record<string, string>)[keyAttr] ?? "";
  const baseUrl = (s as unknown as Record<string, string>)[urlAttr] ?? "";
  return [name, apiKey, baseUrl];
}

/** 返回 OpenAI 兼容客户端。 */
export function getLlmClient(
  provider?: string | null,
  opts: { apiKey?: string | null; baseUrl?: string | null } = {},
  s: Settings = settings,
): OpenAI {
  const [, resolvedKey, resolvedUrl] = resolveProvider(provider, s);
  const key = opts.apiKey !== undefined && opts.apiKey !== null ? opts.apiKey : resolvedKey;
  if (!key) {
    throw new Error(
      `未配置 LLM 密钥（provider=${provider || DEFAULT_PROVIDER}），请在设置中填写`,
    );
  }
  const finalUrl = opts.baseUrl !== undefined && opts.baseUrl !== null ? opts.baseUrl : resolvedUrl;
  return new OpenAI({ apiKey: key, baseURL: finalUrl || undefined });
}

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: unknown[];
}

/** 便捷的非流式聊天调用。 */
export async function chat(
  prompt: string,
  model?: string | null,
  jsonMode = false,
  provider?: string | null,
  s: Settings = settings,
): Promise<string> {
  const client = getLlmClient(provider, {}, s);
  const completion = await client.chat.completions.create({
    model: model || s.rag_model,
    messages: [
      { role: "system", content: "You are a helpful assistant." },
      { role: "user", content: prompt },
    ],
    ...(jsonMode ? { response_format: { type: "json_object" } } : {}),
  });
  return completion.choices[0]?.message?.content ?? "";
}

/** Embedding 客户端（RAG 与 Web 召回共用）。 */
export function getEmbeddingClient(
  s: Settings = settings,
): OpenAI {
  const key = s.dashscope_api_key;
  if (!key) throw new Error("未配置 DASHSCOPE_API_KEY，无法调用 Embedding");
  return new OpenAI({ apiKey: key, baseURL: s.dashscope_base_url || undefined });
}

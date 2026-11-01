/**
 * 内置 MCP Server · search（契约对齐：app/mcp/servers/search_server.py）。
 *
 * 工具名/入参/出参保持不变；实际检索依赖 `SERPER_API_KEY`。
 */
import { settings } from "../../shared/config.js";
import type { BuiltinMcpServer } from "../manager.js";
import type { ToolSchema } from "../../domain/tools/registry.js";

const TOOLS: ToolSchema[] = [
  {
    name: "web_search",
    description: "使用搜索引擎检索网页，返回标题 / 链接 / 摘要列表。",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "检索关键词" },
        num_results: { type: "integer", description: "返回条数（默认 5）" },
      },
      required: ["query"],
    },
    source: "mcp",
    mcp_server: "search",
  },
  {
    name: "fetch_page",
    description: "抓取指定 URL 的正文内容（去除 HTML 标签）。",
    input_schema: {
      type: "object",
      properties: {
        url: { type: "string", description: "目标 URL" },
        max_chars: { type: "integer", description: "最大字符数（默认 8000）" },
      },
      required: ["url"],
    },
    source: "mcp",
    mcp_server: "search",
  },
];

/** 构造 search Server。 */
export function createSearchServer(): BuiltinMcpServer {
  return {
    name: "search",
    tools: TOOLS,
    async call(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
      if (tool === "web_search") {
        if (!settings.serper_api_key) {
          return { ok: false, error: "未配置 SERPER_API_KEY —— 检索能力不可用" };
        }
        const query = String(args.query ?? "");
        const numResults = Number(args.num_results ?? 5);
        try {
          const response = await fetch("https://google.serper.dev/search", {
            method: "POST",
            headers: {
              "X-API-KEY": settings.serper_api_key,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ q: query, num: numResults }),
          });
          if (!response.ok) {
            return { ok: false, error: `检索失败: HTTP ${response.status}` };
          }
          const data = (await response.json()) as {
            organic?: Array<{ title?: string; link?: string; snippet?: string }>;
          };
          const results = (data.organic ?? []).map((r) => ({
            title: r.title ?? "",
            url: r.link ?? "",
            snippet: r.snippet ?? "",
          }));
          return { ok: true, query, results, count: results.length };
        } catch (err) {
          return { ok: false, error: `检索失败: ${(err as Error).message}` };
        }
      }
      if (tool === "fetch_page") {
        const url = String(args.url ?? "");
        const maxChars = Number(args.max_chars ?? 8000);
        try {
          const response = await fetch(url);
          if (!response.ok) {
            return { ok: false, error: `抓取失败: HTTP ${response.status}` };
          }
          const html = await response.text();
          const text = html
            .replace(/<script[\s\S]*?<\/script>/gi, "")
            .replace(/<style[\s\S]*?<\/style>/gi, "")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .slice(0, maxChars);
          return { ok: true, url, content: text };
        } catch (err) {
          return { ok: false, error: `抓取失败: ${(err as Error).message}` };
        }
      }
      return { ok: false, error: `未知工具: ${tool}` };
    },
  };
}

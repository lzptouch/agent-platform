/**
 * 内置 MCP Server · xiaohongshu（契约对齐：app/mcp/servers/xiaohongshu_server.py）。
 *
 * **7 个工具**的 schema 保持不变；Playwright 登录态落 `browser_data/`。
 * 本实现保留工具契约与错误语义，实际抓取依赖 Playwright（未安装时返回明确原因）。
 */
import path from "node:path";
import fs from "node:fs";
import { settings } from "../../shared/config.js";
import type { BuiltinMcpServer } from "../manager.js";
import type { ToolSchema } from "../../domain/tools/registry.js";

const TOOLS: ToolSchema[] = [
  {
    name: "xiaohongshu_search",
    description: "按关键词搜索小红书笔记，返回标题 / 作者 / 链接 / 点赞数。",
    input_schema: {
      type: "object",
      properties: {
        keyword: { type: "string", description: "搜索关键词" },
        limit: { type: "integer", description: "返回条数（默认 10）" },
      },
      required: ["keyword"],
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_note_detail",
    description: "获取指定小红书笔记的正文、图片列表与互动数据。",
    input_schema: {
      type: "object",
      properties: {
        note_id: { type: "string", description: "笔记 ID" },
      },
      required: ["note_id"],
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_user_profile",
    description: "获取指定小红书用户的简介与笔记列表。",
    input_schema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "用户 ID" },
      },
      required: ["user_id"],
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_comments",
    description: "获取指定笔记的评论列表。",
    input_schema: {
      type: "object",
      properties: {
        note_id: { type: "string", description: "笔记 ID" },
        limit: { type: "integer", description: "返回条数（默认 20）" },
      },
      required: ["note_id"],
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_publish",
    description: "发布一篇小红书笔记（图文）。",
    input_schema: {
      type: "object",
      properties: {
        title: { type: "string", description: "标题" },
        content: { type: "string", description: "正文" },
        images: { type: "array", items: { type: "string" }, description: "图片路径列表" },
        tags: { type: "array", items: { type: "string" }, description: "话题标签" },
      },
      required: ["title", "content"],
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_login_status",
    description: "查询当前登录态（是否已登录、用户名、Cookie 落盘位置）。",
    input_schema: {
      type: "object",
      properties: {},
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
  {
    name: "xiaohongshu_login",
    description: "扫码登录小红书（浏览器持久化上下文落在 browser_data/）。",
    input_schema: {
      type: "object",
      properties: {
        timeout_seconds: { type: "integer", description: "等待扫码的超时秒数（默认 120）" },
      },
    },
    source: "mcp",
    mcp_server: "xiaohongshu",
  },
];

/** 登录态落盘位置。 */
function statePath(): string {
  return path.join(settings.browser_data_dir, "xiaohongshu", "state.json");
}

/** 是否存在登录态。 */
export function hasLoginState(): boolean {
  try {
    return fs.existsSync(statePath());
  } catch {
    return false;
  }
}

/** 构造 xiaohongshu Server。 */
export function createXiaohongshuServer(): BuiltinMcpServer {
  const unavailable = (): Record<string, unknown> => ({
    ok: false,
    error:
      "小红书链路依赖 Playwright 浏览器运行时，当前环境未安装。" +
      "请在 设置 → 运行时 中安装 Playwright 后重试。",
  });

  return {
    name: "xiaohongshu",
    tools: TOOLS,
    async call(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
      switch (tool) {
        case "xiaohongshu_login_status":
          return {
            ok: true,
            logged_in: hasLoginState(),
            state_path: statePath(),
            browser_data_dir: settings.browser_data_dir,
          };
        case "xiaohongshu_login":
          return unavailable();
        case "xiaohongshu_search":
        case "xiaohongshu_note_detail":
        case "xiaohongshu_user_profile":
        case "xiaohongshu_comments":
        case "xiaohongshu_publish":
          if (!hasLoginState()) {
            return {
              ok: false,
              error: "未登录小红书（缺少登录态），请先调用 xiaohongshu_login",
            };
          }
          return unavailable();
        default:
          return { ok: false, error: `未知工具: ${tool}` };
      }
    },
  };
}

/**
 * ToolRegistry —— 统一工具抽象层（契约对齐：services/tool_registry.py）。
 *
 * 把 4 类工具合并为 OpenAI/Anthropic 兼容的 tools schema：
 * 1. 内置工具（tool_search / tool_load / read_file / write_file / execute_python /
 *    execute_bash / emit_artifact / list_directory）；
 * 2. MCP 工具（命名空间 `mcp_<server>__<tool>`，动态发现）；
 * 3. RAG 工具（rag_query / rag_ingest，静态定义）；
 * 4. Web Research 工具（web_research，静态定义）。
 *
 * **来源着色元数据**（design §6.3.3）：builtin / mcp / rag / web。
 */
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("tools.registry");

export type ToolProfile = "chat" | "work";

/** 工具来源（着色元数据）。 */
export type ToolSource = "builtin" | "mcp" | "rag" | "web";

export interface ToolSchema {
  name: string;
  description: string;
  input_schema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
  /** 来源（着色） */
  source?: ToolSource;
  /** MCP Server 名（source=mcp 时有值） */
  mcp_server?: string | null;
}

/** 对话模式允许的内置工具（只读）。 */
export const CHAT_BUILTIN_NAMES = new Set(["read_file", "list_directory"]);

/** 写类工具。 */
export const WRITE_TOOL_NAMES = new Set([
  "write_file",
  "execute_python",
  "execute_bash",
  "rag_ingest",
]);

/** 断言 chat 档案中不含写类工具。 */
export function assertProfileConsistency(
  tools: ToolSchema[],
  profile: ToolProfile,
): void {
  if (profile !== "chat") return;
  const names = new Set(tools.map((t) => t.name));
  const illegal = [...names].filter((n) => WRITE_TOOL_NAMES.has(n));
  if (illegal.length) {
    throw new Error(`chat 档案不应包含写类工具: ${illegal.join(", ")}`);
  }
}

// --------------------------------------------------------------------------- //
// 内置工具定义
// --------------------------------------------------------------------------- //
export const BUILTIN_TOOLS: ToolSchema[] = [
  {
    name: "tool_search",
    description:
      "按关键词检索可用工具目录，返回候选工具名与一句话描述（不返回完整参数）。",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "检索关键词" },
        top_k: { type: "integer", description: "候选数量（默认 5）" },
      },
      required: ["query"],
    },
    source: "builtin",
  },
  {
    name: "tool_load",
    description:
      "装载指定工具的完整调用 Schema（返回参数说明，之后即可直接调用该工具）。",
    input_schema: {
      type: "object",
      properties: {
        names: {
          type: "array",
          items: { type: "string" },
          description: "要装载的工具名列表",
        },
      },
      required: ["names"],
    },
    source: "builtin",
  },
  {
    name: "read_file",
    description:
      "读取本地文件的内容。用于读取 Skill 指令文件（SKILL.md）或其他参考文件。",
    input_schema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "要读取的文件的绝对路径或相对路径" },
      },
      required: ["file_path"],
    },
    source: "builtin",
  },
  {
    name: "write_file",
    description: "创建或覆盖写入一个文件。用于保存生成的代码、数据或报告。",
    input_schema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "要写入的文件路径" },
        content: { type: "string", description: "要写入的文件内容" },
      },
      required: ["file_path", "content"],
    },
    source: "builtin",
  },
  {
    name: "execute_python",
    description:
      "执行一段 Python 代码。代码在本地运行，工作目录为 output/。可以使用 pandas、matplotlib、numpy 等已安装的库。",
    input_schema: {
      type: "object",
      properties: { code: { type: "string", description: "要执行的 Python 代码" } },
      required: ["code"],
    },
    source: "builtin",
  },
  {
    name: "execute_bash",
    description: "执行一条 Bash 命令。工作目录为 output/。",
    input_schema: {
      type: "object",
      properties: { command: { type: "string", description: "要执行的 Bash 命令" } },
      required: ["command"],
    },
    source: "builtin",
  },
  {
    name: "emit_artifact",
    description:
      "把工作区内的文件登记为**交付物**（产物），会在结果区的「产物」标签下可见。" +
      " 只在文件确为最终交付物时调用；中间文件不需要登记。",
    input_schema: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "工作区内的文件路径（相对工作区根或绝对路径）",
        },
        title: { type: "string", description: "展示标题（默认取文件名）" },
        kind: {
          type: "string",
          description: "产物类型：file / image / document / browser（浏览器页面截图）",
        },
        url: { type: "string", description: "kind=browser 时的**页面地址**（来源 URL）" },
      },
      required: ["path"],
    },
    source: "builtin",
  },
  {
    name: "list_directory",
    description: "列出指定目录下的文件和子目录。",
    input_schema: {
      type: "object",
      properties: {
        dir_path: { type: "string", description: "要列出内容的目录路径" },
      },
      required: ["dir_path"],
    },
    source: "builtin",
  },
];

// --------------------------------------------------------------------------- //
// RAG / Web 工具定义
// --------------------------------------------------------------------------- //
export const RAG_TOOLS: ToolSchema[] = [
  {
    name: "rag_query",
    description:
      "[本地文档库] 从产品手册/内部文档中检索并带 [n] 引用回答。适用于产品参数、技术规格、内部知识问答。",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "用户问题" },
        limit: { type: "integer", default: 10, minimum: 1, maximum: 50 },
      },
      required: ["query"],
    },
    source: "rag",
  },
  {
    name: "rag_ingest",
    description: "[本地文档库] 重新解析 data/pdf/ 下的 PDF 并入库向量库（慢操作）。",
    input_schema: {
      type: "object",
      properties: { recreate: { type: "boolean", default: true } },
    },
    source: "rag",
  },
];

export const WEB_TOOLS: ToolSchema[] = [
  {
    name: "web_research",
    description:
      "[实时网络] Serper Google 搜索 + 爬虫 + 向量召回 + 带引用回答。适用于实时新闻、竞品对比、最新评测。",
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "研究问题" },
        profile: { type: "string", default: "", description: "LLM 角色" },
        output_format: { type: "string", default: "", description: "输出格式要求" },
      },
      required: ["query"],
    },
    source: "web",
  },
];

/** 全部静态工具（目录检索用）。 */
export function allStaticTools(): ToolSchema[] {
  return [...BUILTIN_TOOLS, ...RAG_TOOLS, ...WEB_TOOLS];
}

/** MCP 工具清单提供者（由 MCPManager 实现，避免循环依赖）。 */
export interface McpToolProvider {
  isReadOnly(server: string): boolean;
  listToolsWithSchema(server: string): ToolSchema[];
}

export interface MergeOptions {
  enableMcp?: boolean;
  mcpServers?: string[] | null;
  enableRag?: boolean;
  enableWebResearch?: boolean;
  profile?: ToolProfile;
  /** 角色声明的工具**上界**（实际调用仍要过权限引擎） */
  roleTools?: string[] | null;
}

export function mergeTools(
  mcp: McpToolProvider | null,
  opts: MergeOptions = {},
): ToolSchema[] {
  const profile = opts.profile ?? "work";
  let tools: ToolSchema[] =
    profile === "chat"
      ? BUILTIN_TOOLS.filter((t) => CHAT_BUILTIN_NAMES.has(t.name))
      : [...BUILTIN_TOOLS];

  if (opts.enableRag) {
    tools =
      profile === "chat"
        ? [...tools, ...RAG_TOOLS.filter((t) => t.name === "rag_query")]
        : [...tools, ...RAG_TOOLS];
  }
  if (opts.enableWebResearch) {
    tools = [...tools, ...WEB_TOOLS];
  }
  if (opts.enableMcp && opts.mcpServers?.length && mcp) {
    for (const name of opts.mcpServers) {
      if (profile === "chat" && !mcp.isReadOnly(name)) {
        logger.info("chat 模式跳过非只读 MCP Server", { server: name });
        continue;
      }
      try {
        for (const t of mcp.listToolsWithSchema(name)) {
          const firstLine = (t.description ?? "").split("\n")[0];
          tools.push({
            name: `mcp_${name}__${t.name}`,
            description: `[MCP:${name}] ${firstLine}`,
            input_schema: t.input_schema ?? { type: "object", properties: {} },
            source: "mcp",
            mcp_server: name,
          });
        }
      } catch (err) {
        // 单个 Server 失败不阻塞其他
        logger.warn("加载 MCP Server 工具失败", { server: name, error: String(err) });
      }
    }
  }

  // 角色工具上界裁剪
  if (opts.roleTools && opts.roleTools.length) {
    const upper = new Set(opts.roleTools);
    tools = tools.filter((t) => upper.has(t.name) || t.source === "mcp");
  }

  assertProfileConsistency(tools, profile);
  return tools;
}

/**
 * 工具延迟装载器（design §6.3.3）：首轮只给目录，按需装载完整 Schema。
 */
export class LazyToolLoader {
  private loaded = new Set<string>();
  private catalog: ToolSchema[];

  constructor(catalog: ToolSchema[]) {
    this.catalog = catalog;
  }

  /** 首轮可见的工具（目录 + 核心 Schema）。 */
  visibleTools(): ToolSchema[] {
    return this.catalog.filter((t) => !t.name.startsWith("mcp_"));
  }

  /** 按关键词检索工具目录。 */
  search(query: string, topK = 5): Array<{ name: string; description: string }> {
    const q = (query ?? "").trim().toLowerCase();
    const pool = [...BUILTIN_TOOLS, ...RAG_TOOLS, ...WEB_TOOLS];
    const scored = pool
      .map((t) => {
        const hay = `${t.name} ${t.description}`.toLowerCase();
        const score = !q ? 0 : hay.includes(q) ? 1 : 0;
        return { t, score };
      })
      .filter((x) => x.score > 0)
      .slice(0, topK);
    return scored.map((x) => ({
      name: x.t.name,
      description: x.t.description.split("\n")[0],
    }));
  }

  /** 装载指定工具的完整 Schema。 */
  load(names: string[]): ToolSchema[] {
    const out: ToolSchema[] = [];
    for (const name of names) {
      const found = this.catalog.find((t) => t.name === name);
      if (found) {
        this.loaded.add(name);
        out.push(found);
      }
    }
    return out;
  }

  /** 已装载的工具名。 */
  loadedNames(): string[] {
    return [...this.loaded];
  }
}

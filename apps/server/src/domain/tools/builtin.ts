/**
 * 内置工具实现与分发（契约对齐：services/tool_registry.py 的执行部分）。
 *
 * 工具执行结果统一为 `{ok, ...}` 结构；异常一律转为 `{ok: false, error}`，
 * **不抛穿**（Agent 循环会把错误作为 tool_result 回喂给模型）。
 */
import fs from "node:fs";
import path from "node:path";
import { getDb, toJson } from "../../db/client.js";
import { utcNow } from "../../db/schema.js";
import { getLogger } from "../../shared/logger.js";
import { codeExecutor, type LocalCodeExecutor } from "./executor.js";
import { LazyToolLoader, allStaticTools, type ToolSchema } from "./registry.js";

const logger = getLogger("tools.builtin");

export interface ToolCallContext {
  /** run 绑定的 workspace 根 */
  workspaceRoot?: string | null;
  /** 产物登记回调（由 Agent 循环注入） */
  emitArtifact?: (payload: {
    path: string;
    title?: string | null;
    kind?: string;
    url?: string | null;
  }) => Record<string, unknown>;
  /** RAG 查询回调 */
  ragQuery?: (query: string, limit: number) => Promise<Record<string, unknown>>;
  /** RAG 入库回调 */
  ragIngest?: (recreate: boolean) => Promise<Record<string, unknown>>;
  /** Web 研究回调 */
  webResearch?: (payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  /** 延迟装载器 */
  loader?: LazyToolLoader;
  /** 敏感信息扫描（写前） */
  scanSensitive?: (content: string) => { action: string; processed: string; hits: unknown[] };
}

/** 解析工具入参中的路径（相对工作目录）。 */
function resolveTarget(cwd: string, target: string): string {
  return path.isAbsolute(target) ? target : path.resolve(cwd, target);
}

/** 读文件。 */
export function toolReadFile(
  ctx: ToolCallContext,
  input: Record<string, unknown>,
): Record<string, unknown> {
  const filePath = String(input.file_path ?? "");
  if (!filePath) return { ok: false, error: "缺少 file_path" };
  const cwd = ctx.workspaceRoot ?? codeExecutor.cwdDir();
  const resolved = resolveTarget(cwd, filePath);
  const denied = codeExecutor.checkAllowed(resolved, false);
  if (denied) return { ok: false, error: denied };
  try {
    const content = fs.readFileSync(resolved, "utf-8");
    return { ok: true, path: resolved, content, size: content.length };
  } catch (err) {
    return { ok: false, error: `读取失败: ${(err as Error).message}` };
  }
}

/** 写文件。 */
export function toolWriteFile(
  ctx: ToolCallContext,
  input: Record<string, unknown>,
): Record<string, unknown> {
  const filePath = String(input.file_path ?? "");
  const content = String(input.content ?? "");
  if (!filePath) return { ok: false, error: "缺少 file_path" };
  const cwd = ctx.workspaceRoot ?? codeExecutor.cwdDir();
  const resolved = resolveTarget(cwd, filePath);
  const denied = codeExecutor.checkAllowed(resolved, true);
  if (denied) return { ok: false, error: denied };

  // 写前敏感信息扫描
  let finalContent = content;
  if (ctx.scanSensitive) {
    try {
      const scan = ctx.scanSensitive(content);
      if (scan.action === "deny") {
        return { ok: false, error: "内容命中敏感信息策略（deny），已拒绝写入" };
      }
      finalContent = scan.processed;
    } catch (err) {
      logger.warn("敏感信息扫描失败（按放行处理）", { error: String(err) });
    }
  }

  try {
    fs.mkdirSync(path.dirname(resolved), { recursive: true });
    fs.writeFileSync(resolved, finalContent, "utf-8");
    const size = Buffer.byteLength(finalContent, "utf-8");
    return { ok: true, path: resolved, size, bytes: size };
  } catch (err) {
    return { ok: false, error: `写入失败: ${(err as Error).message}` };
  }
}

/** 列目录。 */
export function toolListDirectory(
  ctx: ToolCallContext,
  input: Record<string, unknown>,
): Record<string, unknown> {
  const dirPath = String(input.dir_path ?? "");
  if (!dirPath) return { ok: false, error: "缺少 dir_path" };
  const cwd = ctx.workspaceRoot ?? codeExecutor.cwdDir();
  const resolved = resolveTarget(cwd, dirPath);
  try {
    const entries = fs.readdirSync(resolved, { withFileTypes: true });
    return {
      ok: true,
      path: resolved,
      entries: entries.map((e) => ({
        name: e.name,
        is_dir: e.isDirectory(),
        size: e.isFile() ? fs.statSync(path.join(resolved, e.name)).size : null,
      })),
    };
  } catch (err) {
    return { ok: false, error: `列目录失败: ${(err as Error).message}` };
  }
}

/** 登记产物。 */
export function toolEmitArtifact(
  ctx: ToolCallContext,
  input: Record<string, unknown>,
): Record<string, unknown> {
  if (!ctx.emitArtifact) {
    return { ok: false, error: "当前上下文不支持产物登记" };
  }
  const target = String(input.path ?? "");
  if (!target) return { ok: false, error: "缺少 path" };
  const cwd = ctx.workspaceRoot ?? codeExecutor.cwdDir();
  const resolved = resolveTarget(cwd, target);
  const denied = codeExecutor.checkAllowed(resolved, false);
  if (denied) return { ok: false, error: denied };
  if (!fs.existsSync(resolved)) {
    return { ok: false, error: `文件不存在: ${resolved}` };
  }
  try {
    const stat = fs.statSync(resolved);
    const rec = ctx.emitArtifact({
      path: resolved,
      title: input.title ? String(input.title) : path.basename(resolved),
      kind: input.kind ? String(input.kind) : "file",
      url: input.url ? String(input.url) : null,
    });
    return { ok: true, registered: true, artifact: rec, size: stat.size };
  } catch (err) {
    return { ok: false, error: `产物登记失败: ${(err as Error).message}` };
  }
}

/** 工具目录检索。 */
export function toolSearch(ctx: ToolCallContext, input: Record<string, unknown>): Record<string, unknown> {
  const query = String(input.query ?? "");
  const topK = Number(input.top_k ?? 5);
  const loader = ctx.loader ?? new LazyToolLoader(allStaticTools());
  const candidates = loader.search(query, Number.isFinite(topK) ? topK : 5);
  return { ok: true, query, candidates, count: candidates.length };
}

/** 装载工具完整 Schema。 */
export function toolLoad(ctx: ToolCallContext, input: Record<string, unknown>): Record<string, unknown> {
  const names = Array.isArray(input.names) ? (input.names as string[]) : [];
  if (!names.length) return { ok: false, error: "缺少 names" };
  const loader = ctx.loader ?? new LazyToolLoader(allStaticTools());
  const loaded = loader.load(names);
  return { ok: true, loaded: loaded.map((t: ToolSchema) => t.name), tools: loaded };
}

/**
 * 分发一个内置工具调用。
 *
 * 返回 `{ok, ...}`；未知工具返回 `ok: false`。
 */
export async function dispatchBuiltinTool(
  name: string,
  input: Record<string, unknown>,
  ctx: ToolCallContext,
  executor: LocalCodeExecutor = codeExecutor,
): Promise<Record<string, unknown>> {
  switch (name) {
    case "read_file":
      return toolReadFile(ctx, input);
    case "write_file":
      return toolWriteFile(ctx, input);
    case "list_directory":
      return toolListDirectory(ctx, input);
    case "emit_artifact":
      return toolEmitArtifact(ctx, input);
    case "tool_search":
      return toolSearch(ctx, input);
    case "tool_load":
      return toolLoad(ctx, input);
    case "execute_python":
      return executor.executePython(String(input.code ?? ""));
    case "execute_bash":
      return executor.executeBash(String(input.command ?? ""));
    case "rag_query": {
      if (!ctx.ragQuery) return { ok: false, error: "RAG 未启用" };
      return ctx.ragQuery(String(input.query ?? ""), Number(input.limit ?? 10));
    }
    case "rag_ingest": {
      if (!ctx.ragIngest) return { ok: false, error: "RAG 未启用" };
      return ctx.ragIngest(Boolean(input.recreate ?? true));
    }
    case "web_research": {
      if (!ctx.webResearch) return { ok: false, error: "Web Research 未启用" };
      return ctx.webResearch(input);
    }
    default:
      return { ok: false, error: `未知工具: ${name}` };
  }
}

/** 产物登记（直接落库）。 */
export function registerArtifact(payload: {
  runId: string;
  workspaceId?: string | null;
  path: string;
  title?: string | null;
  kind?: string;
  url?: string | null;
}): Record<string, unknown> {
  const db = getDb();
  let size: number | null = null;
  let mime: string | null = null;
  try {
    const stat = fs.statSync(payload.path);
    size = stat.size;
    const ext = path.extname(payload.path).toLowerCase();
    mime =
      ext === ".png"
        ? "image/png"
        : ext === ".jpg" || ext === ".jpeg"
          ? "image/jpeg"
          : ext === ".pdf"
            ? "application/pdf"
            : ext === ".md"
              ? "text/markdown"
              : ext === ".html"
                ? "text/html"
                : "text/plain";
  } catch {
    // 文件可能不存在
  }
  const previewable = mime?.startsWith("image/") || mime === "application/pdf" ? 1 : 0;
  db.prepare(
    `INSERT INTO artifacts (run_id, workspace_id, path, title, mime, kind, size,
      previewable, url, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    payload.runId,
    payload.workspaceId ?? null,
    payload.path,
    payload.title ?? null,
    mime,
    payload.kind ?? "other",
    size,
    previewable,
    payload.url ?? null,
    utcNow(),
  );
  const row = db.prepare("SELECT * FROM artifacts ORDER BY id DESC LIMIT 1").get() as Record<
    string,
    unknown
  >;
  return row;
}

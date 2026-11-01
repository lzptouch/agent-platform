/**
 * 系统路由（契约对齐：app/api/v1/system.py）。
 *
 * 端点：`GET /health` · `GET /metrics` · `GET /cost/estimate`
 */
import type { FastifyInstance } from "fastify";
import { settings } from "../../shared/config.js";
import { getLogger } from "../../shared/logger.js";
import { priceTable, getPrice } from "../../domain/accounting/pricing.js";
import { getDb } from "../../db/client.js";
import { TABLE_NAMES } from "../../db/schema.js";
import { listTables } from "../../db/migrate.js";
import { getServices } from "../context.js";
import { HttpError } from "../../shared/errors.js";

const logger = getLogger("routes.system");

export async function registerSystemRoutes(app: FastifyInstance): Promise<void> {
  // ⚠️ **响应键必须与契约一致**（Python 侧 `system.py::health`）——
  //    前端「系统状态」页逐个读这些字段：
  //    `output_dir` / `api_key_configured` / `llm_available` / `web_search_available`
  //    / `research_configured` / `research_search_provider` / `rag_collection`
  //    / `rag_entities` / `research_enabled` / `research_total_tasks`
  //    / `research_running_tasks` / `mcp_servers_available` / `scheduler` / `database`
  // 此前只返回 7 个字段 → 系统状态页大面积空白（P8-02 实测）。
  app.get("/api/v1/health", async () => {
    const db = getDb();
    let database = "ok";
    try {
      db.prepare("SELECT 1").get();
    } catch {
      database = "error";
    }
    let ragEntities = -1;
    try {
      const row = db
        .prepare("SELECT COUNT(*) AS c FROM chunks")
        .get() as { c: number } | undefined;
      ragEntities = row?.c ?? 0;
    } catch {
      ragEntities = -1;
    }
    const research = getServices().research;
    return {
      status: "ok",
      app: settings.app_name,
      version: settings.app_version,
      skills_loaded: getServices().skill.listSkills().length,
      api_key_configured: settings.has_api_key,
      output_dir: settings.output_dir,
      mcp_servers_available: getServices().mcp.listServers().length,
      rag_collection: settings.milvus_collection,
      rag_entities: ragEntities,
      web_search_available: settings.web_search_available,
      llm_available: settings.llm_available,
      // ---- Research 链路 ----
      research_enabled: true,
      research_search_provider: researchSearchProvider(),
      research_configured: settings.research_configured,
      research_total_tasks: research.list().length,
      research_running_tasks: research.list().filter((t) => t.status !== "done" && t.status !== "failed" && t.status !== "cancelled").length,
      // ---- 扩展 ----
      database,
      scheduler: getServices().scheduler.health(),
      // 兼容字段
      desktop_mode: settings.desktop_mode,
      has_api_key: settings.has_api_key,
      scheduler_enabled: settings.scheduler_enabled,
    };
  });

  app.get("/api/v1/metrics", async () => {
    const db = getDb();
    const tables = listTables();
    const counts: Record<string, number> = {};
    for (const table of TABLE_NAMES) {
      if (!tables.includes(table)) continue;
      try {
        const row = db.prepare(`SELECT COUNT(*) AS c FROM ${table}`).get() as { c: number };
        counts[table] = row?.c ?? 0;
      } catch {
        counts[table] = 0;
      }
    }
    // ---- 契约对齐（Python 侧 `system.py::metrics`）----
    // 「最近 24 小时」口径：`runs_24h`（`runs_today` 为**兼容旧字段**的别名）
    const since24h = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const runRows = db
      .prepare(
        `SELECT status, duration_ms FROM runs
         WHERE created_at >= ? OR status IN ('running','queued','awaiting_approval')`,
      )
      .all(since24h) as Array<{ status: string; duration_ms: number | null }>;
    const terminal = runRows.filter((r) =>
      ["success", "failed", "skipped", "interrupted", "rejected"].includes(r.status),
    );
    const success = terminal.filter((r) => r.status === "success").length;
    const skipped = terminal.filter((r) => r.status === "skipped").length;
    const durations = terminal
      .map((r) => r.duration_ms)
      .filter((d): d is number => typeof d === "number" && Number.isFinite(d))
      .sort((a, b) => a - b);
    const pct = (p: number): number | null => {
      if (!durations.length) return null;
      const idx = Math.min(durations.length - 1, Math.floor((durations.length - 1) * p));
      return durations[idx];
    };
    const round4 = (n: number | null): number | null =>
      n === null ? null : Math.round(n * 1e4) / 1e4;

    return {
      // ---- Python 侧同名字段（口径一致）----
      concurrency: {
        running: runRows.filter((r) => r.status === "running").length,
        limit: settings.schedule_max_concurrent,
      },
      success_rate: round4(terminal.length ? success / terminal.length : null),
      success_rate_excluding_skipped: round4(
        terminal.length - skipped > 0 ? success / (terminal.length - skipped) : null,
      ),
      runs_24h: runRows.length,
      runs_today: runRows.length, // 兼容旧字段
      terminal_runs_24h: terminal.length,
      duration_ms: { samples: durations.length, p50: pct(0.5), p90: pct(0.9) },
      llm: { provider: "dashscope", model: settings.default_model },
      mcp_connections: getServices().mcp.listServers().length,
      ts: new Date().toISOString(),
      // ---- 扩展字段 ----
      tables: tables.length,
      counts,
      uptime_seconds: Math.round(process.uptime()),
      memory_bytes: process.memoryUsage().rss,
      node_version: process.version,
    };
  });

  // ⚠️ **语义与键名必须与契约一致**（Python 侧 `context.py::cost_estimate`）：
  //    `{"percentiles": {p50, p90, samples}, "pricing": [...]}`。
  //    此前实现的是「按 token 数估算单价」，键名完全不同 → 前端
  //    `RunCostBar` 读 `est.percentiles.p50` 恒为 undefined（功能失效）。
  app.get("/api/v1/cost/estimate", async (req) => {
    const q = req.query as Record<string, string>;
    const model = q.model ?? settings.default_model;
    return {
      percentiles: costPercentiles(model),
      pricing: priceTable(),
    };
  });

  // 保留：按 token 数估算单次成本（**扩展端点**，不占用契约路径）
  app.get("/api/v1/cost/estimate/tokens", async (req) => {
    const q = req.query as Record<string, string>;
    const model = q.model ?? settings.default_model;
    const promptTokens = Number(q.prompt_tokens ?? 0);
    const completionTokens = Number(q.completion_tokens ?? 0);
    if (!Number.isFinite(promptTokens) || !Number.isFinite(completionTokens)) {
      throw new HttpError(400, "prompt_tokens / completion_tokens 必须是数字");
    }
    const price = getPrice(model);
    const cost =
      (promptTokens / 1000) * price.input_per_1k +
      (completionTokens / 1000) * price.output_per_1k;
    return {
      model,
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      estimated_cost: Math.round(cost * 1e8) / 1e8,
      price: {
        provider: price.provider,
        input_per_1k: price.input_per_1k,
        output_per_1k: price.output_per_1k,
        cached_input_per_1k: price.cached_input_per_1k,
      },
      table: priceTable(),
    };
  });

  logger.debug("系统路由已注册");
}

/**
 * 同类任务的历史消耗区间（p50~p90）。
 *
 * 契约对齐：Python 侧 `app/services/exec/accounting.py::cost_percentiles`
 * —— 取最近 `limit*4` 条 `llm_calls.cost`，p50 取中位数、p90 取 90% 分位。
 */
export function costPercentiles(
  model?: string | null,
  limit = 50,
): { p50: number | null; p90: number | null; samples: number } {
  const db = getDb();
  let sql = "SELECT cost FROM llm_calls WHERE cost IS NOT NULL";
  const params: unknown[] = [];
  if (model) {
    sql += " AND model = ?";
    params.push(model);
  }
  sql += " ORDER BY id DESC LIMIT ?";
  params.push(limit * 4);
  const rows = db.prepare(sql).all(...params) as Array<{ cost: number }>;
  const costs = rows.map((r) => r.cost).filter((c) => Number.isFinite(c));
  if (!costs.length) return { p50: null, p90: null, samples: 0 };
  costs.sort((a, b) => a - b);
  const mid = Math.floor(costs.length / 2);
  const p50 =
    costs.length % 2 === 0 ? (costs[mid - 1] + costs[mid]) / 2 : costs[mid];
  const idx = Math.min(costs.length - 1, Math.floor(costs.length * 0.9));
  const round8 = (n: number): number => Math.round(n * 1e8) / 1e8;
  return { p50: round8(p50), p90: round8(costs[idx]), samples: costs.length };
}

/**
 * Research 链路的检索提供方（`bocha` / `serper` / `none`）。
 *
 * 契约对齐：Python 侧 `get_search_client().provider`。
 */
function researchSearchProvider(): string {
  if (settings.bocha_api_key) return "bocha";
  if (settings.serper_api_key) return "serper";
  return "none";
}

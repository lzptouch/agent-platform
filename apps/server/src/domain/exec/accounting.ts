/**
 * LLM 调用计量（契约对齐：services/exec/accounting.py）。
 *
 * 每次调用落一行 `llm_calls`，含**单价快照**（改价不影响历史金额）。
 */
import { getDb } from "../../db/client.js";
import { utcNow } from "../../db/schema.js";
import { calculateCost } from "../accounting/pricing.js";
import { getLogger } from "../../shared/logger.js";

const logger = getLogger("exec.accounting");

export interface CallUsage {
  model: string;
  promptTokens: number;
  completionTokens: number;
  cachedTokens?: number;
  latencyMs: number;
  role?: string;
  provider?: string;
}

/** 记录一次 LLM 调用。 */
export function recordCall(
  usage: CallUsage,
  runId: string | null = null,
  sessionId: string | null = null,
): void {
  try {
    const [cost, snapshot] = calculateCost(
      usage.model,
      usage.promptTokens,
      usage.completionTokens,
      { cachedTokens: usage.cachedTokens ?? 0 },
    );
    const db = getDb();
    db.prepare(
      `INSERT INTO llm_calls (run_id, session_id, model, provider, role, prompt_tokens,
        completion_tokens, cached_tokens, latency_ms, price_snapshot, cost, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).run(
      runId,
      sessionId,
      usage.model,
      usage.provider ?? "dashscope",
      usage.role ?? "agent",
      usage.promptTokens,
      usage.completionTokens,
      usage.cachedTokens ?? 0,
      usage.latencyMs,
      JSON.stringify(snapshot),
      cost,
      utcNow(),
    );
  } catch (err) {
    logger.warn("计量记录失败（不影响主流程）", { error: String(err) });
  }
}

export interface RunUsageAggregate {
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  estimated_cost: number;
}

/** 聚合某 run 的 LLM 计量（**纯读**，不写回 runs 行）。 */
export function aggregateRun(runId: string): RunUsageAggregate {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT COALESCE(SUM(prompt_tokens), 0) AS p,
              COALESCE(SUM(completion_tokens), 0) AS c,
              COUNT(*) AS n,
              COALESCE(SUM(cost), 0) AS cost
       FROM llm_calls WHERE run_id = ?`,
    )
    .get(runId) as { p: number; c: number; n: number; cost: number };
  return {
    prompt_tokens: row?.p ?? 0,
    completion_tokens: row?.c ?? 0,
    llm_calls: row?.n ?? 0,
    estimated_cost: row?.cost ?? 0,
  };
}

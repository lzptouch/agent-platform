/**
 * 模型单价表与成本计算（契约对齐：backend/app/core/pricing.py）。
 *
 * 要点：**单价快照**——调用时把当时的单价写进 `llm_calls.price_snapshot`，
 * 因此**改价不影响历史金额**。
 *
 * 单价单位：每 1000 token 的价格（美元）。
 */
import { settings, type Settings } from "../../shared/config.js";

export interface Price {
  provider: string;
  input_per_1k: number;
  output_per_1k: number;
  cached_input_per_1k: number;
}

export function priceToDict(p: Price): Record<string, unknown> {
  return {
    provider: p.provider,
    input_per_1k: p.input_per_1k,
    output_per_1k: p.output_per_1k,
    cached_input_per_1k: p.cached_input_per_1k,
  };
}

/** 默认单价表（可被 `settings.pricing_json` 覆盖）。 */
export const DEFAULT_PRICES: Record<string, Price> = {
  "qwen-plus": { provider: "dashscope", input_per_1k: 0.0008, output_per_1k: 0.002, cached_input_per_1k: 0 },
  "qwen-max": { provider: "dashscope", input_per_1k: 0.0016, output_per_1k: 0.0064, cached_input_per_1k: 0 },
  "qwen-turbo": { provider: "dashscope", input_per_1k: 0.0004, output_per_1k: 0.0012, cached_input_per_1k: 0 },
  "deepseek-chat": { provider: "deepseek", input_per_1k: 0.00027, output_per_1k: 0.0011, cached_input_per_1k: 0 },
  "deepseek-reasoner": { provider: "deepseek", input_per_1k: 0.00055, output_per_1k: 0.00219, cached_input_per_1k: 0 },
  "gpt-4o": { provider: "openai", input_per_1k: 0.0025, output_per_1k: 0.01, cached_input_per_1k: 0 },
  "gpt-4o-mini": { provider: "openai", input_per_1k: 0.00015, output_per_1k: 0.0006, cached_input_per_1k: 0 },
};

/** 未知模型的兜底单价。 */
export const FALLBACK_PRICE: Price = {
  provider: "unknown",
  input_per_1k: 0.001,
  output_per_1k: 0.003,
  cached_input_per_1k: 0,
};

/** 取模型单价（支持配置覆盖）。 */
export function getPrice(model: string, s: Settings = settings): Price {
  const override = s.pricing_json.trim();
  if (override) {
    try {
      const data = JSON.parse(override) as Record<string, Partial<Price>>;
      const val = data[model];
      if (val) {
        return {
          provider: String(val.provider ?? "unknown"),
          input_per_1k: Number(val.input_per_1k ?? 0),
          output_per_1k: Number(val.output_per_1k ?? 0),
          cached_input_per_1k: Number(val.cached_input_per_1k ?? 0),
        };
      }
    } catch {
      // 配置损坏 → 用默认值
    }
  }
  return DEFAULT_PRICES[model] ?? FALLBACK_PRICE;
}

/** 返回 `[成本, 单价快照]`。 */
export function calculateCost(
  model: string,
  promptTokens: number,
  completionTokens: number,
  opts: { cachedTokens?: number; price?: Price } = {},
  s: Settings = settings,
): [number, Record<string, unknown>] {
  const p = opts.price ?? getPrice(model, s);
  const cachedTokens = opts.cachedTokens ?? 0;
  const billableInput = Math.max(0, promptTokens - cachedTokens);
  const cost =
    (billableInput / 1000) * p.input_per_1k +
    (cachedTokens / 1000) * p.cached_input_per_1k +
    (Math.max(0, completionTokens) / 1000) * p.output_per_1k;
  return [Math.round(cost * 1e8) / 1e8, priceToDict(p)];
}

/** 当前生效的单价表（供设置页展示）。 */
export function priceTable(s: Settings = settings): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = Object.entries(DEFAULT_PRICES).map(
    ([model, p]) => ({ model, ...priceToDict(p) }),
  );
  const override = s.pricing_json.trim();
  if (override) {
    try {
      const data = JSON.parse(override) as Record<string, Partial<Price>>;
      for (const [model, val] of Object.entries(data)) {
        const idx = rows.findIndex((r) => r.model === model);
        const row = {
          model,
          provider: String(val.provider ?? "unknown"),
          input_per_1k: Number(val.input_per_1k ?? 0),
          output_per_1k: Number(val.output_per_1k ?? 0),
          cached_input_per_1k: Number(val.cached_input_per_1k ?? 0),
        };
        if (idx >= 0) rows[idx] = row;
        else rows.push(row);
      }
    } catch {
      // 忽略损坏的覆盖配置
    }
  }
  return rows;
}

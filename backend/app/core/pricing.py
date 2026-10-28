"""模型单价表与成本计算（S5 / WP-5.5）。

要点：**单价快照**——调用时把当时的单价写进 ``llm_calls.price_snapshot``，
因此**改价不影响历史金额**（F-CTX-09）。

单价单位：每 1000 token 的价格（美元）。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class Price:
    """一个模型的单价（每 1000 token）。"""

    provider: str
    input_per_1k: float
    output_per_1k: float
    cached_input_per_1k: float = 0.0

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "input_per_1k": self.input_per_1k,
            "output_per_1k": self.output_per_1k,
            "cached_input_per_1k": self.cached_input_per_1k,
        }


#: 默认单价表（可被 `settings.pricing_json` 覆盖）
DEFAULT_PRICES: dict[str, Price] = {
    "qwen-plus": Price("dashscope", 0.0008, 0.002),
    "qwen-max": Price("dashscope", 0.0016, 0.0064),
    "qwen-turbo": Price("dashscope", 0.0004, 0.0012),
    "deepseek-chat": Price("deepseek", 0.00027, 0.0011),
    "deepseek-reasoner": Price("deepseek", 0.00055, 0.00219),
    "gpt-4o": Price("openai", 0.0025, 0.01),
    "gpt-4o-mini": Price("openai", 0.00015, 0.0006),
}

#: 未知模型的兜底单价
FALLBACK_PRICE = Price("unknown", 0.001, 0.003)


def get_price(model: str) -> Price:
    """取模型单价（支持配置覆盖）。"""
    override = settings.pricing_json.strip()
    if override:
        import json

        try:
            data = json.loads(override)
            for key, val in data.items():
                if key == model:
                    return Price(
                        provider=str(val.get("provider", "unknown")),
                        input_per_1k=float(val.get("input_per_1k", 0)),
                        output_per_1k=float(val.get("output_per_1k", 0)),
                        cached_input_per_1k=float(val.get("cached_input_per_1k", 0)),
                    )
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            pass
    return DEFAULT_PRICES.get(model, FALLBACK_PRICE)


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_tokens: int = 0,
    price: Price | None = None,
) -> tuple[float, dict]:
    """返回 ``(成本, 单价快照)``。

    单价快照与成本**同时**算出——快照随调用落库，之后改价不影响历史金额。
    """
    p = price or get_price(model)
    billable_input = max(0, prompt_tokens - cached_tokens)
    cost = (
        billable_input / 1000 * p.input_per_1k
        + cached_tokens / 1000 * p.cached_input_per_1k
        + max(0, completion_tokens) / 1000 * p.output_per_1k
    )
    return round(cost, 8), p.as_dict()


def price_table() -> list[dict]:
    """当前生效的单价表（供设置页展示）。"""
    rows = [{"model": m, **p.as_dict()} for m, p in DEFAULT_PRICES.items()]
    if settings.pricing_json.strip():
        import json

        try:
            data = json.loads(settings.pricing_json)
            for m, val in data.items():
                rows = [r for r in rows if r["model"] != m]
                rows.append({
                    "model": m,
                    "provider": val.get("provider", "unknown"),
                    "input_per_1k": float(val.get("input_per_1k", 0)),
                    "output_per_1k": float(val.get("output_per_1k", 0)),
                    "cached_input_per_1k": float(val.get("cached_input_per_1k", 0)),
                })
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            pass
    return rows

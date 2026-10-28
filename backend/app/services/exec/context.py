"""上下文预算、裁剪与压缩（S5 / WP-5.2 + WP-5.3）。

三件事：

1. **预算**：token 预算（模型窗口 × 比例）+ 字符预算**双约束**；
2. **裁剪**：保留系统提示 + 最近 N 轮原文 + 高价值工具结果，先丢最旧历史；
3. **压缩**：超过阈值（70% → compact，85% → contextSummary）时用九段结构化模板
   压缩历史，保留最近 N 轮原文，并产出 ``context_compressed`` 事件载荷。

token 估算用字符启发式（``len/4``），不引入 tiktoken 依赖；真实计量由
``llm_calls`` 表在调用后校正。
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 模型窗口（字符/token 估算用）
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "qwen-plus": 128_000,
    "qwen-max": 32_000,
    "qwen-turbo": 128_000,
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}
DEFAULT_CONTEXT_WINDOW = 32_000

#: 占用比例阈值
COMPACT_THRESHOLD = 0.70
SUMMARY_THRESHOLD = 0.85

#: 压缩后保留的最近轮数（原文）
KEEP_RECENT_TURNS = 3

#: 工具结果入库的静态上限（动态截断在此之上再按预算收紧）
TOOL_RESULT_MAX_CHARS = 8000


def estimate_tokens(text: str) -> int:
    """字符启发式的 token 估算（中文按 ~1.5 字符/token，英文 ~4 字符/token）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def estimate_messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_tokens(str(m.get("content") or "")) for m in messages)


@dataclass
class ContextBudget:
    """一次请求的上下文预算。"""

    model: str
    window: int
    ratio: float = 0.85
    max_chars: int = 400_000

    @classmethod
    def for_model(cls, model: str, ratio: float = 0.85) -> "ContextBudget":
        window = MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)
        return cls(model=model, window=window, ratio=ratio, max_chars=int(window * ratio * 4))

    @property
    def token_limit(self) -> int:
        return int(self.window * self.ratio)

    @property
    def char_limit(self) -> int:
        return min(self.max_chars, int(self.window * self.ratio * 4))

    def usage(self, messages: list[dict]) -> dict:
        tokens = estimate_messages_tokens(messages)
        chars = sum(len(str(m.get("content") or "")) for m in messages)
        return {
            "tokens": tokens,
            "chars": chars,
            "ratio": tokens / self.window if self.window else 0.0,
            "token_limit": self.token_limit,
            "char_limit": self.char_limit,
        }


def should_compact(usage_ratio: float) -> bool:
    return usage_ratio >= COMPACT_THRESHOLD


def should_summarize(usage_ratio: float) -> bool:
    return usage_ratio >= SUMMARY_THRESHOLD


@dataclass
class TrimResult:
    messages: list[dict]
    dropped: int = 0
    reason: str = ""


def trim_messages(
    messages: list[dict],
    budget: ContextBudget,
    *,
    keep_recent_turns: int = KEEP_RECENT_TURNS,
) -> TrimResult:
    """裁剪消息列表。

    顺序：**系统提示永不裁** → 保留最近 N 轮原文 → 保留高价值工具结果 →
    先丢最旧的普通历史。
    """
    usage = budget.usage(messages)
    if usage["tokens"] <= budget.token_limit and usage["chars"] <= budget.char_limit:
        return TrimResult(messages=list(messages), dropped=0, reason="within_budget")

    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    # 最近 N 轮（按 user 消息为界）
    user_positions = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    cutoff = user_positions[-keep_recent_turns] if len(user_positions) >= keep_recent_turns else 0
    recent = rest[cutoff:]
    older = rest[:cutoff]

    # 高价值工具结果：错误/警告/关键路径优先保留
    def value(m: dict) -> int:
        if m.get("role") != "tool":
            return 0
        content = str(m.get("content") or "")
        score = 1
        for kw in ("error", "错误", "失败", "Traceback", "warning"):
            if kw.lower() in content.lower():
                score += 5
        if m.get("_important"):
            score += 3
        return score

    # 同价值时**新的优先保留**（索引大者先试）→ 效果是「先丢最旧」
    older_sorted = sorted(enumerate(older), key=lambda kv: (-value(kv[1]), -kv[0]))

    # 从**新到旧**尝试保留（先丢最旧历史），高价值工具结果优先占位
    kept_older: list[dict] = []
    dropped = 0
    for _, m in older_sorted:
        candidate = kept_older + [m] + list(recent)
        u = budget.usage(list(system) + candidate)
        if u["tokens"] <= budget.token_limit and u["chars"] <= budget.char_limit:
            kept_older.append(m)
        else:
            dropped += 1
    # 保持原顺序
    kept_set = {id(m) for m in kept_older}
    ordered_older = [m for m in older if id(m) in kept_set]
    result = list(system) + ordered_older + list(recent)
    return TrimResult(messages=result, dropped=dropped, reason="trimmed")


def truncate_tool_result(content: str, budget_chars: int) -> str:
    """工具结果的动态截断（保留头部与尾部，中间标注省略）。"""
    if len(content) <= budget_chars:
        return content
    head = budget_chars // 3
    tail = budget_chars // 3
    omitted = len(content) - head - tail
    return f"{content[:head]}\n\n... [已省略 {omitted} 字符，全文可回查] ...\n\n{content[-tail:]}"


# --------------------------------------------------------------------------- #
# 九段结构化压缩模板（WP-5.3.2）
# --------------------------------------------------------------------------- #
NINE_SECTIONS = (
    "意图",
    "关键概念",
    "涉及文件",
    "已发生的错误",
    "待解决的问题",
    "用户明确消息",
    "待办事项",
    "当前工作状态",
    "下一步",
)

NINE_SECTION_TEMPLATE = """## 意图
{意图}

## 关键概念
{关键概念}

## 涉及文件
{涉及文件}

## 已发生的错误
{已发生的错误}

## 待解决的问题
{待解决的问题}

## 用户明确消息
{用户明确消息}

## 待办事项
{待办事项}

## 当前工作状态
{当前工作状态}

## 下一步
{下一步}"""


@dataclass
class CompressionResult:
    messages: list[dict]
    summary: str
    before_tokens: int = 0
    after_tokens: int = 0
    mode: str = "compact"  # compact | contextSummary
    sections: list[str] = field(default_factory=list)

    @property
    def saved_tokens(self) -> int:
        return max(0, self.before_tokens - self.after_tokens)

    def event_payload(self) -> dict:
        """``context_compressed`` 事件载荷（可展开查看被压缩内容）。"""
        return {
            "mode": self.mode,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "saved_tokens": self.saved_tokens,
            "sections": self.sections,
            "summary": self.summary,
        }


def build_nine_section_summary(
    *,
    intent: str = "",
    concepts: str = "",
    files: str = "",
    errors: str = "",
    questions: str = "",
    user_messages: str = "",
    todos: str = "",
    current: str = "",
    next_step: str = "",
) -> str:
    """按九段模板生成结构化摘要（缺省项留空但**段位齐全**）。"""
    return NINE_SECTION_TEMPLATE.format(
        意图=intent or "（未记录）",
        关键概念=concepts or "（未记录）",
        涉及文件=files or "（未记录）",
        已发生的错误=errors or "（无）",
        待解决的问题=questions or "（无）",
        用户明确消息=user_messages or "（无）",
        待办事项=todos or "（无）",
        当前工作状态=current or "（未记录）",
        下一步=next_step or "（未记录）",
    )


def extract_sections(summary: str) -> list[str]:
    """从摘要文本里抽回段位名（用于校验与事件载荷）。"""
    found = []
    for name in NINE_SECTIONS:
        if f"## {name}" in summary:
            found.append(name)
    return found


def compress(
    messages: list[dict],
    budget: ContextBudget,
    summary: str,
    *,
    mode: str = "compact",
    keep_recent_turns: int = KEEP_RECENT_TURNS,
) -> CompressionResult:
    """用结构化摘要替换旧历史，保留最近 N 轮原文。"""
    before = estimate_messages_tokens(messages)
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    user_positions = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    cutoff = user_positions[-keep_recent_turns] if len(user_positions) >= keep_recent_turns else 0
    recent = rest[cutoff:]

    compressed: list[dict] = list(system)
    compressed.append({
        "role": "user",
        "content": "[历史摘要]\n" + summary,
        "_compressed": True,
    })
    compressed.extend(recent)
    after = estimate_messages_tokens(compressed)
    return CompressionResult(
        messages=compressed,
        summary=summary,
        before_tokens=before,
        after_tokens=after,
        mode=mode,
        sections=extract_sections(summary),
    )

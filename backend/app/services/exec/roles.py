"""内置角色定义（S5 / WP-5.3 + WP-5.4）。

三个轻量角色，**工具集一律为空**（0 工具权限——它们只产出文本）：

- ``compact``：轻量压缩（70% 阈值触发）；
- ``contextSummary``：强摘要（85% 阈值触发，九段结构）；
- ``memorySelector``：记忆预筛（候选 → 至多 5 条）。

**本阶段用代码内常量**（``roles`` 表属 S6），S6 再把内置角色迁入表，
并保留这里的代码默认值作为回退。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    """角色定义。"""

    name: str
    description: str
    model_tier: str            # light | standard | strong
    tools: tuple[str, ...] = ()  # 内置角色一律为空
    prompt: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "model_tier": self.model_tier,
            "tools": list(self.tools),
        }


COMPACT_PROMPT = """你是一个上下文压缩器。请把给定的对话历史压缩成简短的要点，
保留：用户的明确要求、已确定的结论、涉及的文件路径、待办事项。
不要编造，不要输出寒暄。"""

CONTEXT_SUMMARY_PROMPT = """你是一个结构化摘要器。请把对话历史整理为**九段**结构：
意图 / 关键概念 / 涉及文件 / 已发生的错误 / 待解决的问题 / 用户明确消息 /
待办事项 / 当前工作状态 / 下一步。每段都要有内容（无内容写"（无）"）。"""

MEMORY_SELECTOR_PROMPT = """你是一个记忆筛选器。给定候选记忆（文件名 + 一句话描述 + 标签），
选出与当前任务**最相关**的至多 5 条，只输出文件名，每行一个。"""

BUILTIN_ROLES: dict[str, Role] = {
    "compact": Role(
        name="compact",
        description="轻量上下文压缩（占用达 70% 时触发）",
        model_tier="light",
        tools=(),
        prompt=COMPACT_PROMPT,
    ),
    "contextSummary": Role(
        name="contextSummary",
        description="强结构化摘要（占用达 85% 时触发，九段结构）",
        model_tier="light",
        tools=(),
        prompt=CONTEXT_SUMMARY_PROMPT,
    ),
    "memorySelector": Role(
        name="memorySelector",
        description="记忆预筛（从候选中选至多 5 条）",
        model_tier="light",
        tools=(),
        prompt=MEMORY_SELECTOR_PROMPT,
    ),
}


def get_role(name: str) -> Role:
    role = BUILTIN_ROLES.get(name)
    if role is None:
        raise ValueError(f"未知角色: {name}")
    return role


def role_names() -> list[str]:
    return sorted(BUILTIN_ROLES)

"""角色定义与管理（S6 / WP-6.2、6.9）。

角色字段：身份、擅长领域与边界、工作流程、输出风格、工具集、挂载技能、模型档。

约束：
- **名称唯一**且**创建后不可改名**（对齐竞品约束）；
- 声明的工具集是**上界**（最小权限），实际调用仍要过权限引擎；
- **轻档角色 0 工具**（`compact` / `contextSummary` / `memorySelector` 沿用 S5 定义）。

本阶段把 S5 的代码内常量角色迁入 ``roles`` 表，**代码默认值保留作回退**。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import RoleRow, utc_now

logger = logging.getLogger(__name__)

#: 模型档位
MODEL_TIERS = ("light", "standard", "strong")

#: 轻档角色必须 0 工具
ZERO_TOOL_TIERS = ("light",)


class RoleError(ValueError):
    """角色定义不合法。"""


# --------------------------------------------------------------------------- #
# 内置角色（P2-13 · 从 exec/roles.py 迁入）
# --------------------------------------------------------------------------- #
#: 轻量上下文压缩器
COMPACT_PROMPT = """你是一个上下文压缩器。请把给定的对话历史压缩成简短的要点，
保留：用户的明确要求、已确定的结论、涉及的文件路径、待办事项。
不要编造，不要输出寒暄。"""

#: 结构化摘要器（九段）
CONTEXT_SUMMARY_PROMPT = """你是一个结构化摘要器。请把对话历史整理为**九段**结构：
意图 / 关键概念 / 涉及文件 / 已发生的错误 / 待解决的问题 / 用户明确消息 /
待办事项 / 当前工作状态 / 下一步。每段都要有内容（无内容写"（无）"）。"""

#: 记忆预筛器
MEMORY_SELECTOR_PROMPT = """你是一个记忆筛选器。给定候选记忆（文件名 + 一句话描述 + 标签），
选出与当前任务**最相关**的至多 5 条，只输出文件名，每行一个。"""

#: 三个内置角色的 Prompt（``contextSummary`` 已被九段摘要真正使用——P2-03）
BUILTIN_ROLE_PROMPTS: dict[str, str] = {
    "compact": COMPACT_PROMPT,
    "contextSummary": CONTEXT_SUMMARY_PROMPT,
    "memorySelector": MEMORY_SELECTOR_PROMPT,
}

#: 三个内置角色的元数据（写入 ``roles`` 表）
BUILTIN_ROLE_META: dict[str, dict] = {
    "compact": {
        "description": "轻量上下文压缩（占用达 70% 时触发）",
        "model_tier": "light",
        "tools": (),
    },
    "contextSummary": {
        "description": "强结构化摘要（占用达 85% 时触发，九段结构）",
        "model_tier": "light",
        "tools": (),
    },
    "memorySelector": {
        "description": "记忆预筛（从候选中选至多 5 条）",
        "model_tier": "light",
        "tools": (),
    },
}


@dataclass
class Role:
    """角色定义。"""

    id: int | None
    name: str
    title: str = ""
    identity: str = ""
    expertise: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    workflow: list[str] = field(default_factory=list)
    output_style: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    model_tier: str = "standard"
    builtin: bool = False
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "identity": self.identity,
            "expertise": list(self.expertise),
            "boundaries": list(self.boundaries),
            "workflow": list(self.workflow),
            "output_style": self.output_style,
            "tools": list(self.tools),
            "skills": list(self.skills),
            "model_tier": self.model_tier,
            "builtin": self.builtin,
            "enabled": self.enabled,
        }

    @property
    def tool_budget(self) -> set[str]:
        """声明的工具集（上界）。"""
        return set(self.tools)


def _row_to_role(row: RoleRow) -> Role:
    def _load(raw: str) -> list[str]:
        try:
            val = json.loads(raw or "[]")
            return [str(v) for v in val] if isinstance(val, list) else []
        except json.JSONDecodeError:
            return []

    return Role(
        id=row.id,
        name=row.name,
        title=row.title or "",
        identity=row.identity or "",
        expertise=_load(row.expertise),
        boundaries=_load(row.boundaries),
        workflow=_load(row.workflow),
        output_style=row.output_style or "",
        tools=_load(row.tools_json),
        skills=_load(row.skills_json),
        model_tier=row.model_tier or "standard",
        builtin=bool(row.builtin),
        enabled=bool(row.enabled),
    )


def model_for_tier(tier: str) -> str:
    """档位 → 模型名（轻档用更便宜的模型）。"""
    return {
        "light": "qwen-turbo",
        "standard": "qwen-plus",
        "strong": "qwen-max",
    }.get(tier, "qwen-plus")


class RoleService:
    """角色 CRUD（表为准，代码常量为回退）。"""

    def create(
        self,
        name: str,
        *,
        title: str = "",
        identity: str = "",
        expertise: list[str] | None = None,
        boundaries: list[str] | None = None,
        workflow: list[str] | None = None,
        output_style: str = "",
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        model_tier: str = "standard",
    ) -> Role:
        name = (name or "").strip()
        if not name:
            raise RoleError("角色名不能为空")
        if model_tier not in MODEL_TIERS:
            raise RoleError(f"model_tier 必须是 {'/'.join(MODEL_TIERS)}")
        tools = list(tools or [])
        if model_tier in ZERO_TOOL_TIERS and tools:
            raise RoleError(f"轻档角色（{model_tier}）必须 0 工具")
        with db_session() as db:
            if db.scalar(select(RoleRow).where(RoleRow.name == name)) is not None:
                raise RoleError(f"角色名已存在: {name}")
            row = RoleRow(
                name=name,
                title=title or name,
                identity=identity,
                expertise=json.dumps(list(expertise or []), ensure_ascii=False),
                boundaries=json.dumps(list(boundaries or []), ensure_ascii=False),
                workflow=json.dumps(list(workflow or []), ensure_ascii=False),
                output_style=output_style,
                tools_json=json.dumps(tools, ensure_ascii=False),
                skills_json=json.dumps(list(skills or []), ensure_ascii=False),
                model_tier=model_tier,
                builtin=0,
                enabled=1,
            )
            db.add(row)
            db.flush()
            return _row_to_role(row)

    def update(self, role_id: int, **fields) -> Role:
        """更新角色。**名字不可改**（与竞品约束一致）。"""
        if "name" in fields and fields["name"] is not None:
            raise RoleError("角色创建后不可改名")
        with db_session() as db:
            row = db.get(RoleRow, role_id)
            if row is None:
                raise RoleError(f"角色不存在: {role_id}")
            for key, attr in (
                ("title", "title"), ("identity", "identity"), ("output_style", "output_style"),
            ):
                if fields.get(key) is not None:
                    setattr(row, attr, str(fields[key]))
            for key, attr in (
                ("expertise", "expertise"), ("boundaries", "boundaries"),
                ("workflow", "workflow"), ("tools", "tools_json"), ("skills", "skills_json"),
            ):
                if fields.get(key) is not None:
                    setattr(row, attr, json.dumps(list(fields[key]), ensure_ascii=False))
            if fields.get("model_tier") is not None:
                tier = str(fields["model_tier"])
                if tier not in MODEL_TIERS:
                    raise RoleError(f"model_tier 必须是 {'/'.join(MODEL_TIERS)}")
                row.model_tier = tier
            if fields.get("enabled") is not None:
                row.enabled = 1 if fields["enabled"] else 0
            row.updated_at = utc_now()
            db.flush()
            return _row_to_role(row)

    def get(self, role_id: int) -> Role | None:
        with db_session() as db:
            row = db.get(RoleRow, role_id)
            return _row_to_role(row) if row else None

    def get_by_name(self, name: str) -> Role | None:
        with db_session() as db:
            row = db.scalar(select(RoleRow).where(RoleRow.name == name))
            return _row_to_role(row) if row else None

    def list(self, include_disabled: bool = True) -> list[Role]:
        with db_session() as db:
            stmt = select(RoleRow).order_by(RoleRow.builtin.desc(), RoleRow.id)
            if not include_disabled:
                stmt = stmt.where(RoleRow.enabled == 1)
            return [_row_to_role(r) for r in db.scalars(stmt).all()]

    def delete(self, role_id: int) -> bool:
        with db_session() as db:
            row = db.get(RoleRow, role_id)
            if row is None:
                return False
            if row.builtin:
                raise RoleError("内置角色不可删除")
            db.delete(row)
            return True

    # ------------------------------------------------------------------ #
    # S5 内置角色迁入（代码常量保留为回退）
    # ------------------------------------------------------------------ #
    def sync_builtin_roles(self) -> int:
        """把 S5 的三个内置角色写入 ``roles`` 表（已存在则更新）。"""
        count = 0
        for name, spec in BUILTIN_ROLE_META.items():
            with db_session() as db:
                row = db.scalar(select(RoleRow).where(RoleRow.name == name))
                if row is None:
                    row = RoleRow(name=name)
                    db.add(row)
                row.title = spec["description"]
                row.identity = spec["description"]
                row.tools_json = json.dumps(list(spec["tools"]), ensure_ascii=False)
                row.model_tier = spec["model_tier"]
                row.builtin = 1
                row.enabled = 1
                row.updated_at = utc_now()
                db.flush()
                count += 1
        return count

    def resolve(self, name: str) -> Role:
        """取角色（表优先，缺失时回落代码常量）。"""
        role = self.get_by_name(name)
        if role is not None:
            return role
        # **修复**：此前引用**未定义**的 ``BUILTIN_ROLES``（本模块只有
        # ``BUILTIN_ROLE_META`` / ``BUILTIN_ROLE_PROMPTS``）→ 一旦被调用即 NameError。
        meta = BUILTIN_ROLE_META.get(name)
        if meta is None:
            raise RoleError(f"角色不存在: {name}")
        return Role(
            id=None, name=name,
            title=str(meta.get("title") or name),
            identity=str(meta.get("identity") or meta.get("description") or name),
            tools=list(meta.get("tools") or ()),
            model_tier=str(meta.get("model_tier") or "standard"),
            builtin=True,
        )


_service: RoleService | None = None


def get_role_service() -> RoleService:
    global _service
    if _service is None:
        _service = RoleService()
    return _service

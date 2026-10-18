"""TeamService —— Skill 团队（Expert）管理。

- ``teams`` + ``team_skills`` 两张表；删除团队时会话 ``team_id`` 置 NULL（外键语义）。
- ``resolve()`` 支持 none / sequential / router 三种编排策略；
  router 用 LLM 选 1~2 个 Skill，失败降级为 none，结果缓存 5 分钟。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.db.base import db_session
from app.db.models import SessionRow, TeamRow, TeamSkillRow, utc_now
from app.schemas.team import ResolveOut, ResolvedSkill, TeamOut

if TYPE_CHECKING:
    from app.services.skill_manager import SkillManager

logger = logging.getLogger(__name__)

ROUTER_CACHE_TTL = 300
ROUTER_CACHE_MAX = 256

ROUTER_PROMPT = """你是一个工具调度器。从候选 Skill 中选择最匹配用户请求的 1-2 个。

## 用户请求
{query}

## 候选 Skill（name: description）
{candidates}

## 输出
只输出 JSON 数组，元素必须是候选中的 name，如 ["pdf"]。不要输出其他内容。
"""


class TeamNotFoundError(KeyError):
    pass


class TeamConflictError(ValueError):
    pass


class TeamValidationError(ValueError):
    pass


def _team_to_out(db, row: TeamRow) -> TeamOut:
    members = [m.skill_name for m in sorted(row.members, key=lambda m: m.position)]
    ref = db.scalar(
        select(func.count()).select_from(SessionRow).where(SessionRow.team_id == row.id)
    ) or 0
    return TeamOut(
        id=row.id,
        name=row.name,
        description=row.description,
        skill_names=members,
        prompt_prefix=row.prompt_prefix,
        strategy=row.strategy,  # type: ignore[arg-type]
        enabled=bool(row.enabled),
        reference_count=ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TeamService:
    def __init__(self, skill_manager: SkillManager) -> None:
        self.skill_manager = skill_manager
        self._router_cache: dict[str, tuple[float, list[str]]] = {}

    # ------------------------------------------------------------------ #
    # 校验
    # ------------------------------------------------------------------ #
    def validate_members(self, skill_names: list[str]) -> list[str]:
        """返回不存在的成员名（创建时严格 422）。"""
        known = set(self.skill_manager.skills)
        return [n for n in skill_names if n not in known]

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(self, *, name: str, skill_names: list[str], description: str = "",
               prompt_prefix: str = "", strategy: str = "none") -> TeamOut:
        missing = self.validate_members(skill_names)
        if missing:
            raise TeamValidationError(f"未知 Skill: {', '.join(missing)}")
        with db_session() as db:
            if db.scalar(select(TeamRow).where(TeamRow.name == name)):
                raise TeamConflictError(f"团队名已存在: {name}")
            row = TeamRow(
                name=name, description=description,
                prompt_prefix=prompt_prefix, strategy=strategy,
            )
            db.add(row)
            db.flush()
            for i, skill_name in enumerate(skill_names):
                db.add(TeamSkillRow(team_id=row.id, skill_name=skill_name, position=i))
            db.flush()  # 先落成员再读取（autoflush=False 时 refresh 会过期关联导致读到空）
            db.refresh(row)
            return _team_to_out(db, row)

    def list(self, include_disabled: bool = True) -> list[TeamOut]:
        with db_session() as db:
            stmt = select(TeamRow).order_by(TeamRow.updated_at.desc())
            if not include_disabled:
                stmt = stmt.where(TeamRow.enabled == 1)
            rows = db.scalars(stmt).all()
            return [_team_to_out(db, r) for r in rows]

    def get(self, team_id: str) -> TeamOut | None:
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            return _team_to_out(db, row) if row else None

    def update(self, team_id: str, **fields) -> TeamOut | None:
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            if row is None:
                return None
            if fields.get("name") and fields["name"] != row.name:
                if db.scalar(select(TeamRow).where(TeamRow.name == fields["name"])):
                    raise TeamConflictError(f"团队名已存在: {fields['name']}")
                row.name = fields["name"]
            for key in ("description", "prompt_prefix", "strategy"):
                if fields.get(key) is not None:
                    setattr(row, key, fields[key])
            if fields.get("skill_names") is not None:
                missing = self.validate_members(fields["skill_names"])
                if missing:
                    raise TeamValidationError(f"未知 Skill: {', '.join(missing)}")
                db.execute(delete(TeamSkillRow).where(TeamSkillRow.team_id == team_id))
                for i, skill_name in enumerate(fields["skill_names"]):
                    db.add(TeamSkillRow(team_id=team_id, skill_name=skill_name, position=i))
            row.updated_at = utc_now()
            db.flush()
            db.refresh(row)
            return _team_to_out(db, row)

    def delete(self, team_id: str) -> bool:
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            if row is None:
                return False
            db.execute(
                SessionRow.__table__.update()
                .where(SessionRow.team_id == team_id)
                .values(team_id=None)
            )
            db.delete(row)
            return True

    def set_enabled(self, team_id: str, enabled: bool) -> bool:
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            if row is None:
                return False
            row.enabled = 1 if enabled else 0
            row.updated_at = utc_now()
            return True

    # ------------------------------------------------------------------ #
    # 解析（编排策略）
    # ------------------------------------------------------------------ #
    def resolve(self, team_id: str, query: str = "", mode: str = "work") -> ResolveOut:
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            if row is None:
                raise TeamNotFoundError(team_id)
            members = [m.skill_name for m in sorted(row.members, key=lambda m: m.position)]
            team_name, strategy, prefix, enabled = row.name, row.strategy, row.prompt_prefix, bool(row.enabled)

        warnings: list[str] = []
        degraded = False
        if not enabled:
            warnings.append("团队已禁用")

        available: list[ResolvedSkill] = []
        for i, name in enumerate(members):
            skill = self.skill_manager.get(name)
            if skill is None:
                warnings.append(f"成员 Skill 不存在: {name}")
                continue
            if not skill.get("enabled", True):
                warnings.append(f"成员 Skill 已禁用: {name}")
                continue
            available.append(
                ResolvedSkill(
                    name=name,
                    description=skill["description"],
                    enabled=True,
                    step_index=i + 1 if strategy == "sequential" else None,
                )
            )

        if strategy == "router" and available and query:
            chosen, degraded = self._route(query, available)
            if chosen:
                available = [s for s in available if s.name in chosen]

        prompt_preview = self.skill_manager.build_system_prompt(
            [s.name for s in available],
            mode=mode,
            team={"name": team_name, "prompt_prefix": prefix, "strategy": strategy},
        )
        return ResolveOut(
            team_id=team_id,
            team_name=team_name,
            strategy=strategy,  # type: ignore[arg-type]
            skills=available,
            prompt_preview=prompt_preview,
            degraded=degraded,
            warnings=warnings,
        )

    def _route(self, query: str, candidates: list[ResolvedSkill]) -> tuple[list[str], bool]:
        """LLM 路由；返回 (选中名列表, 是否降级)。"""
        key = hashlib.sha256(
            (query + "|" + ",".join(sorted(s.name for s in candidates))).encode()
        ).hexdigest()
        cached = self._router_cache.get(key)
        if cached and time.time() - cached[0] < ROUTER_CACHE_TTL:
            return cached[1], False

        try:
            from app.core.llm import chat
            from app.core.config import settings as _s

            cand_text = "\n".join(f"- {s.name}: {s.description}" for s in candidates)
            text = chat(
                ROUTER_PROMPT.format(query=query[:2000], candidates=cand_text),
                model=_s.plan_model,
                json_mode=True,
            )
            match = re.search(r"(\[[\s\S]*?\])", text or "")
            names = json.loads(match.group(1)) if match else []
            valid = {s.name for s in candidates}
            chosen = [n for n in names if isinstance(n, str) and n in valid][:2]
            if not chosen:
                return [s.name for s in candidates], True
            if len(self._router_cache) >= ROUTER_CACHE_MAX:
                self._router_cache.clear()
            self._router_cache[key] = (time.time(), chosen)
            return chosen, False
        except Exception as exc:  # noqa: BLE001
            logger.warning("团队 router 失败，降级为全量: %s", exc)
            return [s.name for s in candidates], True

    # ------------------------------------------------------------------ #
    # 供 Agent 使用：团队元数据 + 展开的 Skill 名称
    # ------------------------------------------------------------------ #
    def resolve_for_agent(self, team_id: str, query: str = "", mode: str = "work") -> tuple[list[str], dict, list[str]]:
        result = self.resolve(team_id, query=query, mode=mode)
        team_meta = {
            "id": result.team_id,
            "name": result.team_name,
            "strategy": result.strategy,
            "prompt_prefix": "",
        }
        with db_session() as db:
            row = db.get(TeamRow, team_id)
            if row:
                team_meta["prompt_prefix"] = row.prompt_prefix
        return [s.name for s in result.skills], team_meta, result.warnings

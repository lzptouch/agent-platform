"""Skill 团队模型。"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TeamStrategy = Literal["none", "sequential", "router"]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    skill_names: list[str] = Field(min_length=1)
    description: str = ""
    prompt_prefix: str = ""
    strategy: TeamStrategy = "none"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("团队名称不能为空")
        return v

    @field_validator("skill_names")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for name in v:
            seen[name.strip()] = None
        out = [n for n in seen if n]
        if not out:
            raise ValueError("至少需要一个成员 Skill")
        return out


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    skill_names: list[str] | None = None
    description: str | None = None
    prompt_prefix: str | None = None
    strategy: TeamStrategy | None = None

    @field_validator("skill_names")
    @classmethod
    def _dedupe(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        seen: dict[str, None] = {}
        for name in v:
            seen[name.strip()] = None
        return [n for n in seen if n]


class TeamOut(BaseModel):
    id: str
    name: str
    description: str
    skill_names: list[str]
    prompt_prefix: str
    strategy: TeamStrategy
    enabled: bool
    reference_count: int = 0
    created_at: str
    updated_at: str


class ResolveRequest(BaseModel):
    query: str = ""
    mode: Literal["chat", "work"] = "work"


class ResolvedSkill(BaseModel):
    name: str
    description: str
    enabled: bool = True
    step_index: int | None = None


class ResolveOut(BaseModel):
    team_id: str
    team_name: str
    strategy: TeamStrategy
    skills: list[ResolvedSkill]
    prompt_preview: str
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)

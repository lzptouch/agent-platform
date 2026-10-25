"""定时任务模型。"""
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=20000)
    mode: Literal["chat", "work"] = "work"
    plan_first: bool = False
    team_id: str | None = None
    # 与 RunRequest.skills 语义对齐：null = 不限定（work 全部 / chat 不加载），
    # [] = 不加载任何 Skill，列表 = 仅启用列出的 Skill。
    skills: list[str] | None = None
    enable_mcp: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    enable_rag: bool = False
    enable_web_research: bool = False
    enable_reflection: bool = False
    schedule_kind: Literal["cron", "interval"]
    cron_expr: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    timezone: str = settings.tz
    enabled: bool = True
    allow_unattended_tools: bool = False
    allow_dangerous_tools: bool = False
    daily_run_limit: int = Field(default=settings.schedule_daily_run_limit, ge=1, le=1000)

    @field_validator("timezone")
    @classmethod
    def _tz_valid(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(f"无效时区: {v}")
        return v

    @field_validator("cron_expr")
    @classmethod
    def _cron_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(v.strip())
        except Exception as exc:
            raise ValueError(f"无效 cron 表达式: {exc}")
        return v.strip()

    @model_validator(mode="after")
    def _cross_check(self):
        if (self.cron_expr is None) == (self.interval_seconds is None):
            raise ValueError("cron_expr 与 interval_seconds 必须二选一")
        if self.mode == "chat" and self.plan_first:
            raise ValueError("对话模式不支持 plan_first")
        if self.mode == "work" and self.enabled and not self.allow_unattended_tools:
            raise ValueError("工作模式的启用任务需显式确认 allow_unattended_tools=true")
        if self.team_id and self.skills:
            raise ValueError("team_id 与 skills 互斥，只能二选一")
        return self


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    mode: Literal["chat", "work"] | None = None
    plan_first: bool | None = None
    team_id: str | None = None
    skills: list[str] | None = None
    enable_mcp: bool | None = None
    mcp_servers: list[str] | None = None
    enable_rag: bool | None = None
    enable_web_research: bool | None = None
    enable_reflection: bool | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    timezone: str | None = None
    allow_unattended_tools: bool | None = None
    allow_dangerous_tools: bool | None = None
    daily_run_limit: int | None = Field(default=None, ge=1, le=1000)


class ScheduleOut(BaseModel):
    id: str
    name: str
    prompt: str
    mode: Literal["chat", "work"]
    plan_first: bool
    team_id: str | None = None
    skills: list[str]
    enable_mcp: bool
    mcp_servers: list[str]
    enable_rag: bool
    enable_web_research: bool
    enable_reflection: bool
    schedule_kind: Literal["cron", "interval"]
    cron_expr: str | None = None
    interval_seconds: int | None = None
    timezone: str
    enabled: bool
    allow_unattended_tools: bool
    allow_dangerous_tools: bool
    daily_run_limit: int
    schedule_text: str = ""
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str = "never"
    last_error: str | None = None
    run_count: int = 0
    consecutive_failures: int = 0
    health: str = "ok"
    created_at: str
    updated_at: str


class CronValidateRequest(BaseModel):
    cron_expr: str
    timezone: str = settings.tz


class CronValidateOut(BaseModel):
    valid: bool
    error: str | None = None
    next_runs: list[str] = Field(default_factory=list)

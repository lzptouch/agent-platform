"""定时任务模型。"""
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings


# --------------------------------------------------------------------------- #
# 校验逻辑（**模块级**）—— 创建与更新**共用**
# --------------------------------------------------------------------------- #
def validate_timezone(v: str) -> str:
    """时区合法性（创建 / 更新共用）。"""
    try:
        ZoneInfo(v)
    except ZoneInfoNotFoundError:
        raise ValueError(f"无效时区: {v}")
    return v


def validate_cron(v: str | None) -> str | None:
    """cron 表达式合法性（创建 / 更新共用）。"""
    if v is None:
        return None
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(v.strip())
    except Exception as exc:
        raise ValueError(f"无效 cron 表达式: {exc}")
    return v.strip()


def validate_rrule(v: str | None) -> str | None:
    """RRULE 表达式合法性（创建 / 更新共用）。"""
    if v is None:
        return None
    from app.services.scheduler.rrule import RRULEError, parse

    try:
        parse(v.strip())
    except RRULEError as exc:
        raise ValueError(f"无效 RRULE 表达式: {exc}") from exc
    return v.strip()


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
    schedule_kind: Literal["cron", "interval", "rrule"]
    cron_expr: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    # P2-16：RRULE 表达式（如 ``FREQ=WEEKLY;BYDAY=MO,WE,FR``）
    rrule_expr: str | None = None
    timezone: str = settings.tz
    # P3-02：投递通道配置（此前 ``delivery_json`` **有读无写** → 用户无法配置）
    delivery: dict | None = None
    enabled: bool = True
    allow_unattended_tools: bool = False
    allow_dangerous_tools: bool = False
    daily_run_limit: int = Field(default=settings.schedule_daily_run_limit, ge=1, le=1000)

    @field_validator("timezone")
    @classmethod
    def _tz_valid(cls, v: str) -> str:
        return validate_timezone(v)

    @field_validator("cron_expr")
    @classmethod
    def _cron_valid(cls, v: str | None) -> str | None:
        return validate_cron(v)

    @field_validator("rrule_expr")
    @classmethod
    def _rrule_valid(cls, v: str | None) -> str | None:
        """非法 RRULE 在 **schema 层**就被拒（→ 422），不拖到调度时才炸。"""
        return validate_rrule(v)

    @field_validator("delivery")
    @classmethod
    def _delivery_valid(cls, v: dict | None) -> dict | None:
        """校验投递配置：通道类型必须已知，且每条通道需 ``type``。"""
        if v is None:
            return None
        from app.services.scheduler.delivery import CHANNELS

        if not isinstance(v, dict):
            raise ValueError("delivery 必须是对象")
        channels = v.get("channels") or []
        if not isinstance(channels, list):
            raise ValueError("delivery.channels 必须是数组")
        for ch in channels:
            if not isinstance(ch, dict):
                raise ValueError("delivery.channels 的每一项必须是对象")
            ctype = str(ch.get("type") or "").strip()
            if ctype not in CHANNELS:
                raise ValueError(f"未知投递通道: {ctype}（可选 {CHANNELS}）")
        return {"channels": channels}

    @model_validator(mode="after")
    def _cross_check(self):
        # cron_expr / interval_seconds / rrule_expr **三选一**（P2-16）
        provided = [
            self.cron_expr is not None,
            self.interval_seconds is not None,
            self.rrule_expr is not None,
        ]
        if sum(provided) != 1:
            raise ValueError("cron_expr / interval_seconds / rrule_expr 必须三选一")
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
    rrule_expr: str | None = None
    # P3-02：投递通道配置可更新
    delivery: dict | None = None
    timezone: str | None = None
    allow_unattended_tools: bool | None = None
    allow_dangerous_tools: bool | None = None
    daily_run_limit: int | None = Field(default=None, ge=1, le=1000)

    # **W9-09 / AUD2-M01**：此前 ``ScheduleUpdate`` **没有** ``ScheduleCreate`` 的
    # 那三个 validator → ``PUT`` 一个非法 cron / rrule / timezone 会
    # **先落库**、再在 ``sync_task`` 里抛错（API 500）→ 非法表达式已持久化，
    # 且 job 未重建；后续 ``sync_all_jobs`` 也会持续抛错（仅日志）。
    # 现在：与创建期**共用同一套**校验函数（非法 → 422，DB 不变）。
    @field_validator("timezone")
    @classmethod
    def _tz_valid(cls, v: str | None) -> str | None:
        return None if v is None else validate_timezone(v)

    @field_validator("cron_expr")
    @classmethod
    def _cron_valid(cls, v: str | None) -> str | None:
        return validate_cron(v)

    @field_validator("rrule_expr")
    @classmethod
    def _rrule_valid(cls, v: str | None) -> str | None:
        return validate_rrule(v)

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
    schedule_kind: Literal["cron", "interval", "rrule"]
    cron_expr: str | None = None
    interval_seconds: int | None = None
    rrule_expr: str | None = None
    timezone: str
    delivery: dict | None = None
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

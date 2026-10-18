"""运行账本模型（runs / run_events）。"""
from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "queued", "running", "awaiting_approval", "success",
    "failed", "skipped", "interrupted", "rejected",
]


class RunOut(BaseModel):
    id: str
    task_id: str | None = None
    session_id: str | None = None
    trigger: str
    scheduled_for: str | None = None
    status: RunStatus
    plan: list[dict] | None = None
    meta: dict = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    result_summary: str | None = None
    error: str | None = None
    files: list = Field(default_factory=list)
    created_at: str


class RunEventOut(BaseModel):
    seq: int
    type: str
    payload: dict = Field(default_factory=dict)
    created_at: str


class RunEventPage(BaseModel):
    items: list[RunEventOut]
    last_seq: int
    status: RunStatus
    has_more: bool = False


class PlanApproval(BaseModel):
    edited_plan: list[dict] | None = None


class PlanRejection(BaseModel):
    reason: str = ""

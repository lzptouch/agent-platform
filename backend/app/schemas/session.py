"""会话与消息模型。"""
from typing import Literal

from pydantic import BaseModel, Field

AgentMode = Literal["chat", "work"]


class SessionCreate(BaseModel):
    mode: AgentMode = "chat"
    title: str = ""
    skills: list[str] | None = None
    team_id: str | None = None
    config: dict = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None
    skills: list[str] | None = None
    team_id: str | None = None
    config: dict | None = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    run_id: str | None = None
    seq: int
    role: str
    content: str
    steps: list = Field(default_factory=list)
    files: list = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    created_at: str


class SessionOut(BaseModel):
    id: str
    mode: AgentMode
    title: str
    team_id: str | None = None
    skills: list[str] | None = None
    config: dict = Field(default_factory=dict)
    archived: bool = False
    message_count: int = 0
    created_at: str
    updated_at: str


class SessionDetail(SessionOut):
    messages: list[MessageOut] = Field(default_factory=list)
    has_more: bool = False

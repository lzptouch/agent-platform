"""ORM 模型（SQLAlchemy 2.0 风格）。

时间统一存 UTC ISO8601 字符串（SQLite 无时区类型），前端本地化展示。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    """会话（chat / work 双模式）。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    mode: Mapped[str] = mapped_column(Text, default="work")  # chat | work
    title: Mapped[str] = mapped_column(Text, default="")
    team_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    messages: Mapped[list[MessageRow]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="MessageRow.seq"
    )

    __table_args__ = (Index("idx_sessions_mode_updated", "mode", "updated_at"),)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, default="")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    session: Mapped[SessionRow] = relationship(back_populates="messages")

    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),)


class TeamRow(Base):
    """Skill 团队（一组 Skill + 提示词前缀 + 编排策略）。"""

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    prompt_prefix: Mapped[str] = mapped_column(Text, default="")
    strategy: Mapped[str] = mapped_column(Text, default="none")  # none | sequential | router
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    members: Mapped[list[TeamSkillRow]] = relationship(
        back_populates="team", cascade="all, delete-orphan", order_by="TeamSkillRow.position"
    )


class TeamSkillRow(Base):
    __tablename__ = "team_skills"

    team_id: Mapped[str] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    skill_name: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    team: Mapped[TeamRow] = relationship(back_populates="members")

    __table_args__ = (Index("idx_team_skills_skill", "skill_name"),)


class SkillRecordRow(Base):
    """Skill 元数据（内容真相仍在文件系统，此处仅存索引与启停用状态）。"""

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="builtin")  # builtin | custom
    path: Mapped[str] = mapped_column(Text, default="")
    frontmatter_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    stale: Mapped[int] = mapped_column(Integer, default=0)  # 磁盘已删除
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, default="work")
    plan_first: Mapped[int] = mapped_column(Integer, default=0)
    team_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    enable_json: Mapped[str] = mapped_column(Text, default="{}")
    schedule_kind: Mapped[str] = mapped_column(Text, nullable=False)  # cron | interval
    cron_expr: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, default="Asia/Shanghai")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    allow_unattended_tools: Mapped[int] = mapped_column(Integer, default=0)
    allow_dangerous_tools: Mapped[int] = mapped_column(Integer, default=0)
    daily_run_limit: Mapped[int] = mapped_column(Integer, default=100)
    next_run_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status: Mapped[str] = mapped_column(Text, default="never")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    backoff_until: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (Index("idx_tasks_enabled_next", "enabled", "next_run_at"),)


class RunRow(Base):
    """运行账本：手动 / 定时 / API 统一记录。"""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(Text, default="manual")  # manual | schedule | api
    scheduled_for: Mapped[str | None] = mapped_column(Text, nullable=True)  # 幂等槽位
    status: Mapped[str] = mapped_column(Text, default="queued")
    # queued | running | awaiting_approval | success | failed | skipped | interrupted | rejected
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    events: Mapped[list[RunEventRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEventRow.seq"
    )

    __table_args__ = (
        UniqueConstraint("task_id", "scheduled_for", name="uq_runs_task_slot"),
        Index("idx_runs_task_started", "task_id", "started_at"),
        Index("idx_runs_status", "status"),
    )


class RunEventRow(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    run: Mapped[RunRow] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        Index("idx_run_events_run_seq", "run_id", "seq"),
    )


class SystemLockRow(Base):
    """调度租约（多进程防重）。"""

    __tablename__ = "system_locks"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    renewed_at: Mapped[str] = mapped_column(Text, nullable=False)

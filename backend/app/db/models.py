"""ORM 模型（SQLAlchemy 2.0 风格）。

时间统一存 UTC ISO8601 字符串（SQLite 无时区类型），前端本地化展示。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.orm import declared_attr


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
    mode: Mapped[str] = mapped_column(Text, default="work")  # chat | work（plan 归一为 work + plan_first）
    plan_first: Mapped[int] = mapped_column(Integer, default=0)  # 1 = 先出计划待确认（S1 统一枚举）
    title: Mapped[str] = mapped_column(Text, default="")
    team_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[int] = mapped_column(Integer, default=0)
    # P3-10：**软删除**——DELETE 只写 ``deleted_at`` + ``archived=1``，
    # 消息与 run 记录保留（可回收），不再物理级联删除。
    deleted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    schedule_kind: Mapped[str] = mapped_column(Text, nullable=False)  # cron | interval | rrule
    cron_expr: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rrule_expr: Mapped[str | None] = mapped_column(Text, nullable=True)  # P2-16
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
    trigger: Mapped[str] = mapped_column(Text, default="manual")  # manual | schedule | api | research
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
    # 用量（桌面端展示「任务前后消耗区间与明细」）
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    # P3-07：乐观锁版本列——并发更新同一行时后提交者收到 StaleDataError，
    # 而非「后写覆盖」静默丢失前者修改。
    version_id: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    @declared_attr
    def __mapper_args__(cls) -> dict:
        # P3-07：乐观锁——并发更新同一行时后提交者收到 StaleDataError，
        # 而非「后写覆盖」静默丢失前者修改。
        # 必须用 declared_attr：类定义期列对象尚未解析完成。
        return {"version_id_col": cls.version_id}

    events: Mapped[list[RunEventRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEventRow.seq"
    )

    __table_args__ = (
        UniqueConstraint("task_id", "scheduled_for", name="uq_runs_task_slot"),
        Index("idx_runs_task_started", "task_id", "started_at"),
        Index("idx_runs_status", "status"),
        # P3-08：trigger 枚举约束（此前可写入任意字符串）
        CheckConstraint(
            "trigger IN ('manual','schedule','api','research')",
            name="ck_runs_trigger",
        ),
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


class DesktopPreferenceRow(Base):
    """桌面端配置（单行，``id`` 恒为 1）。"""

    __tablename__ = "desktop_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    workspace_dir: Mapped[str] = mapped_column(Text, default="")
    default_mode: Mapped[str] = mapped_column(Text, default="chat")
    danger_tools: Mapped[int] = mapped_column(Integer, default=0)  # 派生自 permission_rules
    notify_on_run: Mapped[int] = mapped_column(Integer, default=1)
    notify_channel: Mapped[str] = mapped_column(Text, default="system")  # system | toast | off
    remote_mode: Mapped[int] = mapped_column(Integer, default=0)  # 0=local 1=remote
    remote_base: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)


class PermissionRuleRow(Base):
    """权限规则（S2 扩展：scope ∈ tool | file | command | network | action）。

    - ``pattern``：按 scope 语义 —— file=glob / command=前缀 / network=域名后缀 / tool=命名空间前缀 / action=动作名；
    - ``priority``：数值小者先匹配（内置规则 <100，用户规则默认 100）；
    - ``workspace_id``：NULL=全局；S2 期间存工作目录标识（sha1(绝对路径)[:12]），S3 建表后映射；
    - ``origin``：builtin | user | enterprise；
    - ``expires_at``：可选过期时间（过期规则视为不存在）。
    """

    __tablename__ = "permission_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)  # deny | ask | allow
    risk: Mapped[str] = mapped_column(Text, default="normal")  # normal | elevated | critical
    workspace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    origin: Mapped[str] = mapped_column(Text, default="user")
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        UniqueConstraint("scope", "pattern", "workspace_id", name="uq_permission_rules_triplet"),
        Index("idx_permission_rules_lookup", "scope", "priority"),
    )


class PermissionDecisionRow(Base):
    """权限决策日志（每次判定留痕：谁、什么、被哪条规则、为什么）。"""

    __tablename__ = "permission_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # allow | ask | deny
    matched_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)  # user | policy | timeout
    status: Mapped[str] = mapped_column(Text, default="resolved")  # pending | resolved
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    resolved_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_permission_decisions_run", "run_id"),
        Index("idx_permission_decisions_status", "status"),
    )

class WorkspaceRow(Base):
    """工作空间实体（一任务一空间，运行期锁定）。"""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | archived
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (Index("idx_workspaces_status", "status"),)


class RagDocumentRow(Base):
    """RAG 入库台账（批次 03 / WP-3.1）。

    幂等键 ``doc_id`` = sha256(文件绝对路径 | 内容哈希)：
    同一文件内容不变 → 重复入库直接跳过（chunk 不累积）。
    """

    __tablename__ = "rag_documents"

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    collection: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (Index("idx_rag_documents_source", "source_path"),)


class ChangeRow(Base):
    """逐文件变更（前后哈希 + 快照引用 + 操作类型），支撑 diff 与回退。"""

    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    op: Mapped[str] = mapped_column(Text, nullable=False)  # create | modify | delete | revert
    before_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    size_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        Index("idx_changes_run", "run_id"),
        Index("idx_changes_workspace", "workspace_id"),
    )


class ArtifactRow(Base):
    """产物登记（交付物与中间文件分离）。"""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, default="other")
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previewable: Mapped[int] = mapped_column(Integer, default=0)
    # F-UX-02：浏览器类产物的**页面地址**（截图文件之外的来源 URL）
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        Index("idx_artifacts_run", "run_id"),
        Index("idx_artifacts_workspace", "workspace_id"),
    )

class LlmCallRow(Base):
    """LLM 调用计量（每次调用一行；含**单价快照**，历史金额不随改价而变）。"""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, default="dashscope")
    role: Mapped[str] = mapped_column(Text, default="agent")  # agent | compact | contextSummary | memorySelector
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    price_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        Index("idx_llm_calls_run", "run_id"),
        Index("idx_llm_calls_session", "session_id"),
    )


class MemoryIndexRow(Base):
    """记忆索引（增量刷新；支持按作用域预筛，不扫描全量文件）。"""

    __tablename__ = "memory_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)  # user | workspace | project
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    size: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (Index("idx_memory_index_scope", "scope"),)

class RoleRow(Base):
    """角色定义（S6）：身份 / 边界 / 流程 / 输出风格 / 工具集 / 模型档。

    - 名称唯一且**创建后不可改名**（对齐竞品约束）；
    - ``tools_json`` 是声明的**上界**，实际调用仍要过权限引擎（最小权限）。
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    identity: Mapped[str] = mapped_column(Text, default="")
    expertise: Mapped[str] = mapped_column(Text, default="[]")
    boundaries: Mapped[str] = mapped_column(Text, default="[]")
    workflow: Mapped[str] = mapped_column(Text, default="[]")
    output_style: Mapped[str] = mapped_column(Text, default="")
    tools_json: Mapped[str] = mapped_column(Text, default="[]")
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    model_tier: Mapped[str] = mapped_column(Text, default="standard")  # light | standard | strong
    builtin: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"), Index("idx_roles_enabled", "enabled"))


class PluginRow(Base):
    """插件包（S6）：版本、扫描结果、安装状态。"""

    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, default="local")
    status: Mapped[str] = mapped_column(Text, default="installed")  # installed | rolled_back
    scan_result: Mapped[str] = mapped_column(Text, default="{}")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    installed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_plugins_name_version"),
        Index("idx_plugins_name", "name"),
    )


class BoardItemRow(Base):
    """黑板任务项（S6）：状态机 + 依赖图。"""

    __tablename__ = "board_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="pending")
    # pending | ready | running | done | blocked | failed
    assignee: Mapped[str | None] = mapped_column(Text, nullable=True)
    deps_json: Mapped[str] = mapped_column(Text, default="[]")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)
    updated_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        Index("idx_board_items_board", "board_id"),
        Index("idx_board_items_status", "status"),
    )


class AgentMessageRow(Base):
    """Agent 间消息（S6）：``to_role`` 有值=定向消息；``to_role`` 为空=通知（广播）。"""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, default="message")  # message | notification
    content: Mapped[str] = mapped_column(Text, default="")
    refs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(Text, default=utc_now)

    __table_args__ = (
        Index("idx_agent_messages_board", "board_id"),
        Index("idx_agent_messages_to_role", "to_role"),
    )


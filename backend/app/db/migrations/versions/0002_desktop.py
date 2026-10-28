"""桌面端 schema：desktop_preferences / permission_rules + runs 用量字段

0001 的 upgrade 走 ``Base.metadata.create_all``，因此**新装环境**在 0001 阶段
就会建好本迁移涉及的两张新表与 runs 的新增列；而**老环境**（0001 已执行过）
的库里没有它们。本迁移因此必须**完全幂等**：建表 / 加列前先用 inspector 判存在。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


INITIAL_RULES = [
    # (scope, target, decision)
    ("tool", "read_file", "allow"),
    ("tool", "list_directory", "allow"),
    ("tool", "write_file", "ask"),
    ("tool", "execute_python", "ask"),
    ("tool", "execute_bash", "ask"),
    ("action", "batch_delete", "deny"),
    ("action", "system_config_write", "deny"),
    ("action", "external_script_exec", "ask"),
]

RUN_USAGE_COLUMNS = [
    ("prompt_tokens", sa.Integer()),
    ("completion_tokens", sa.Integer()),
    ("llm_calls", sa.Integer()),
    ("tool_calls", sa.Integer()),
    ("estimated_cost", sa.Float()),
]


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    if "desktop_preferences" not in tables:
        op.create_table(
            "desktop_preferences",
            sa.Column("id", sa.Integer(), primary_key=True, default=1),
            sa.Column("workspace_dir", sa.Text(), nullable=False, server_default=""),
            sa.Column("default_mode", sa.Text(), nullable=False, server_default="chat"),
            sa.Column("danger_tools", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notify_on_run", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("notify_channel", sa.Text(), nullable=False, server_default="system"),
            sa.Column("remote_mode", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("remote_base", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
        )

    if "permission_rules" not in tables:
        op.create_table(
            "permission_rules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope", sa.Text(), nullable=False),
            sa.Column("target", sa.Text(), nullable=False),
            sa.Column("decision", sa.Text(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_hit_at", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("scope", "target", name="uq_permission_rules_scope_target"),
        )
        op.create_index("idx_permission_rules_scope", "permission_rules", ["scope"])

    if "runs" in tables:
        existing = _column_names("runs")
        for name, col_type in RUN_USAGE_COLUMNS:
            if name not in existing:
                op.add_column("runs", sa.Column(name, col_type, nullable=True))

    # 初始规则与默认配置（仅在空表时写入，避免覆盖用户已有设置）
    now = _utc_now()
    if "permission_rules" in _table_names():
        count = bind.execute(sa.text("SELECT COUNT(*) FROM permission_rules")).scalar() or 0
        if count == 0:
            # 新装环境（0001 用当前 ORM 建表）已经是 S2 之后的结构（pattern 而非 target）；
            # 老环境才是旧结构。两套结构都要能写入，否则**全新数据库会在本迁移崩掉**。
            columns = _column_names("permission_rules")
            if "target" in columns:
                for scope, target, decision in INITIAL_RULES:
                    bind.execute(
                        sa.text(
                            "INSERT INTO permission_rules (scope, target, decision, hit_count, updated_at)"
                            " VALUES (:scope, :target, :decision, 0, :updated_at)"
                        ),
                        {"scope": scope, "target": target, "decision": decision, "updated_at": now},
                    )
            else:
                for scope, pattern, decision in INITIAL_RULES:
                    bind.execute(
                        sa.text(
                            "INSERT INTO permission_rules"
                            " (scope, pattern, decision, risk, workspace_id, priority, origin,"
                            "  expires_at, hit_count, last_hit_at, updated_at)"
                            " VALUES (:scope, :pattern, :decision, 'normal', NULL, 100, 'builtin',"
                            "         NULL, 0, NULL, :updated_at)"
                        ),
                        {"scope": scope, "pattern": pattern, "decision": decision, "updated_at": now},
                    )
    if "desktop_preferences" in _table_names():
        count = bind.execute(sa.text("SELECT COUNT(*) FROM desktop_preferences")).scalar() or 0
        if count == 0:
            bind.execute(
                sa.text(
                    "INSERT INTO desktop_preferences"
                    " (id, workspace_dir, default_mode, danger_tools, notify_on_run,"
                    "  notify_channel, remote_mode, remote_base, updated_at)"
                    " VALUES (1, '', 'chat', 0, 1, 'system', 0, '', :updated_at)"
                ),
                {"updated_at": now},
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()

    if "runs" in tables:
        existing = _column_names("runs")
        for name, _col_type in reversed(RUN_USAGE_COLUMNS):
            if name in existing:
                op.drop_column("runs", name)

    if "permission_rules" in tables:
        op.drop_index("idx_permission_rules_scope", table_name="permission_rules")
        op.drop_table("permission_rules")
    if "desktop_preferences" in tables:
        op.drop_table("desktop_preferences")


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

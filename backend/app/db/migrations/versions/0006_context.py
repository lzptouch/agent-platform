"""上下文经济性与成本计量（S5 / WP-5.5 + WP-5.4）。

新增两表：
- ``llm_calls``：每次 LLM 调用的计量（模型 / provider / 输入输出 token / 延迟 /
  **单价快照**）。单价快照保证"历史金额不随改价而变"；
- ``memory_index``：记忆索引（path / summary / tags / scope / last_used_at），
  支持增量刷新与 Top-K 预筛（不扫描全量）。

可回滚。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "llm_calls"):
        op.create_table(
            "llm_calls",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Text(), nullable=True),
            sa.Column("session_id", sa.Text(), nullable=True),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False, server_default="dashscope"),
            sa.Column("role", sa.Text(), nullable=False, server_default="agent"),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            # 单价快照（调用时取值）——历史金额不随改价而变
            sa.Column("price_snapshot", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_llm_calls_run", "llm_calls", ["run_id"])
        op.create_index("idx_llm_calls_session", "llm_calls", ["session_id"])

    if not _has_table(bind, "memory_index"):
        op.create_table(
            "memory_index",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("scope", sa.Text(), nullable=False),   # user | workspace | project
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_used_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_memory_index_scope", "memory_index", ["scope"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("memory_index", "llm_calls"):
        if _has_table(bind, table):
            op.drop_table(table)

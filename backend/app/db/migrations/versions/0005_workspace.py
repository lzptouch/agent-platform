"""工作空间、变更与产物（S3 / WP-3.1）。

新增三表：
- ``workspaces``：工作空间实体（一任务一空间，运行期锁定）；
- ``changes``：逐文件变更（前后哈希 + 快照引用 + 操作类型），支撑 diff 与回退；
- ``artifacts``：产物登记（交付物与中间文件分离）。

幂等：三表均已存在则跳过。可回滚。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "workspaces"):
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("root_path", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),  # active | archived
            sa.Column("manifest_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_workspaces_status", "workspaces", ["status"])

    if not _has_table(bind, "changes"):
        op.create_table(
            "changes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("workspace_id", sa.Text(), nullable=True),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("op", sa.Text(), nullable=False),  # create | modify | delete | revert
            sa.Column("before_hash", sa.Text(), nullable=True),
            sa.Column("after_hash", sa.Text(), nullable=True),
            sa.Column("snapshot_ref", sa.Text(), nullable=True),
            sa.Column("tool", sa.Text(), nullable=False),
            sa.Column("size_before", sa.Integer(), nullable=True),
            sa.Column("size_after", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_changes_run", "changes", ["run_id"])
        op.create_index("idx_changes_workspace", "changes", ["workspace_id"])

    if not _has_table(bind, "artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("workspace_id", sa.Text(), nullable=True),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("mime", sa.Text(), nullable=True),
            sa.Column("kind", sa.Text(), nullable=False, server_default="other"),
            sa.Column("size", sa.Integer(), nullable=True),
            sa.Column("previewable", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_artifacts_run", "artifacts", ["run_id"])
        op.create_index("idx_artifacts_workspace", "artifacts", ["workspace_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("artifacts", "changes", "workspaces"):
        if _has_table(bind, table):
            op.drop_table(table)

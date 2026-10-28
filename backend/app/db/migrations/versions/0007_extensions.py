"""扩展三层与多 Agent（S6 / WP-6.2、6.4、6.7、6.8）。

新增四表：
- ``roles``：角色定义（身份/边界/流程/风格/工具集/模型档/挂载技能）；
- ``plugins``：插件包（版本、扫描结果、安装状态）；
- ``board_items``：黑板任务项（状态机 + 依赖图）；
- ``agent_messages``：Agent 间消息（定向消息 / 通知两种通道）。

可回滚。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False),          # 唯一且创建后不可改名
            sa.Column("title", sa.Text(), nullable=False, server_default=""),
            sa.Column("identity", sa.Text(), nullable=False, server_default=""),
            sa.Column("expertise", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("boundaries", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("workflow", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("output_style", sa.Text(), nullable=False, server_default=""),
            sa.Column("tools_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("skills_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("model_tier", sa.Text(), nullable=False, server_default="standard"),
            sa.Column("builtin", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("name", name="uq_roles_name"),
        )
        op.create_index("idx_roles_enabled", "roles", ["enabled"])

    if not _has_table(bind, "plugins"):
        op.create_table(
            "plugins",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False, server_default="local"),
            sa.Column("status", sa.Text(), nullable=False, server_default="installed"),
            sa.Column("scan_result", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("manifest_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("installed_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("name", "version", name="uq_plugins_name_version"),
        )
        op.create_index("idx_plugins_name", "plugins", ["name"])

    if not _has_table(bind, "board_items"):
        op.create_table(
            "board_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("board_id", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            # pending | ready | running | done | blocked | failed
            sa.Column("assignee", sa.Text(), nullable=True),
            sa.Column("deps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_board_items_board", "board_items", ["board_id"])
        op.create_index("idx_board_items_status", "board_items", ["status"])

    if not _has_table(bind, "agent_messages"):
        op.create_table(
            "agent_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("board_id", sa.Text(), nullable=True),
            sa.Column("from_role", sa.Text(), nullable=True),
            sa.Column("to_role", sa.Text(), nullable=True),   # NULL = 通知（广播）
            sa.Column("kind", sa.Text(), nullable=False, server_default="message"),
            # message | notification
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("refs_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("idx_agent_messages_board", "agent_messages", ["board_id"])
        op.create_index("idx_agent_messages_to_role", "agent_messages", ["to_role"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("agent_messages", "board_items", "plugins", "roles"):
        if _has_table(bind, table):
            op.drop_table(table)

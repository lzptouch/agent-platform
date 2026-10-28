"""mode 枚举归一（S1 / WP-1.4）。

背景：``mode`` 曾在三处各取一子集（``sessions.mode`` 仅 chat|work、
``RunRequest.mode`` 仅 chat|work、``DesktopService.VALID_MODES`` 多了 plan），
导致同一概念三套取值。S1 统一为：

- **对外唯一取值集合**：``chat | plan | work``；
- **落库**：``chat | work``，``plan`` 归一为 ``work`` + ``plan_first=1``；
- **plan_first 独立成列**（与 ``scheduled_tasks`` 已有做法一致），便于按模式过滤。

本迁移：① 给 sessions 增加 plan_first 列；② 把历史遗留的 mode='plan' 行归一。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("sessions")}

    if "plan_first" not in cols:
        op.add_column(
            "sessions",
            sa.Column("plan_first", sa.Integer(), nullable=False, server_default="0"),
        )

    # 历史遗留：mode='plan' → work + plan_first=1
    bind.execute(
        sa.text("UPDATE sessions SET mode='work', plan_first=1 WHERE mode='plan'")
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("sessions")}
    if "plan_first" in cols:
        # 回滚：把 plan 会话还原成 mode='plan'（依赖 plan_first 标记，信息不丢）
        bind.execute(
            sa.text("UPDATE sessions SET mode='plan' WHERE plan_first=1")
        )
        op.drop_column("sessions", "plan_first")

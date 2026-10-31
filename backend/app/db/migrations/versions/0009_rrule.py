"""0009 · 定时任务支持 RRULE（P2-16 / R-17 / G-34）

背景：``app/services/scheduler/rrule.py``（251 行，支持
``FREQ/INTERVAL/BYDAY/BYMONTHDAY/BYHOUR/BYMINUTE/COUNT/UNTIL``）
写好后**从未被调度器调用**——``scheduled_tasks`` 表没有 RRULE 表达式列，
``schedule_kind`` 只有 ``cron`` / ``interval``。

本迁移只做一件事：加 ``rrule_expr`` 列（可空，不影响既有库）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("scheduled_tasks")}
    if "rrule_expr" not in cols:
        op.add_column("scheduled_tasks", sa.Column("rrule_expr", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("scheduled_tasks")}
    if "rrule_expr" in cols:
        op.drop_column("scheduled_tasks", "rrule_expr")

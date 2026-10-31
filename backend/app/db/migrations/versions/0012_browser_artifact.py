"""0012 · 产物加 ``url`` 列（F-UX-02 浏览器视图）

**目的**：浏览器类产物（自动化任务页面截图）需要记录**来源页面地址**，
否则前端「浏览器」视图只能显示一张截图、无法回溯到页面。

- 只加列，不改既有数据；
- ``url`` 可空 → 既有产物不受影响。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # **幂等**：``0001_init`` 用 ORM ``create_all`` 建表 → 新装库里
    # ``artifacts`` **已含** ``url`` 列（模型已更新）→ 直接加列会报
    # ``duplicate column name: url``。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("artifacts")}
    if "url" in existing:
        return
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_column("url")

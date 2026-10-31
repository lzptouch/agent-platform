"""0011 · 会话软删除（P3-10）

- ``sessions`` 增加 ``deleted_at`` 列；
- DELETE 会话改为写 ``deleted_at`` + ``archived=1``（消息保留）；
- 提供「永久删除」端点（管理员用）做真正的物理删除。

**注意**：``0001`` 用当前 ORM 建表（``Base.metadata.create_all``），因此
**全新数据库**里 ``sessions`` 已含 ``deleted_at``；而**既有库**（0010 时代）
没有该列。这里用「先 inspect 再按需加列」的模式，两种库都能正确升级
（与 ``0009`` 同一套路）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("sessions")}
    if "deleted_at" not in cols:
        op.add_column("sessions", sa.Column("deleted_at", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("sessions")}
    if "deleted_at" in cols:
        op.drop_column("sessions", "deleted_at")

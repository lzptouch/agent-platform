"""0010 · 数据约束与乐观锁（P3-07 / P3-08 / P3-13）

三处改动：

1. **P3-08** —— ``runs.trigger`` 加 ``CheckConstraint``（此前可写入任意字符串）；
2. **P3-07** —— ``runs`` 加 ``version_id`` 列并启用 SQLAlchemy 乐观锁
   （并发更新同一行时后提交者收到 ``StaleDataError``，而非静默覆盖）；
3. **P3-13** —— ``skills.frontmatter_json`` 列已有但**无写入方**，
   本迁移不删列（保留兼容），由服务层补写入（见 ``skill_manager._sync_db``）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---- P3-08：runs.trigger 枚举约束 -------------------------------- #
    # 先清洗历史非法值：``trigger`` 此前**无任何约束**，可能已写入过
    # 任意字符串（如测试遗留的 'test'）→ 不清洗则重建表时 CHECK 失败。
    bind.execute(sa.text(
        "UPDATE runs SET trigger='manual' "
        "WHERE trigger NOT IN ('manual','schedule','api','research')"
    ))
    # **必须在同一个 batch 里做两件事**——SQLite 的 batch 模式每次调用都会
    # 重建临时表并复制数据；拆成两个 batch 会导致第二次重建时列已存在
    # （duplicate column name: version_id）。
    with op.batch_alter_table("runs") as batch:
        # P3-08：trigger 枚举约束
        batch.create_check_constraint(
            "ck_runs_trigger",
            "trigger IN ('manual','schedule','api','research')",
        )
        # P3-07：乐观锁版本列
        batch.add_column(
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("version_id")
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("ck_runs_trigger", type_="check")

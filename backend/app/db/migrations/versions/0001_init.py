"""初始 schema：sessions/messages/teams/team_skills/skills/scheduled_tasks/runs/run_events/system_locks

teams 与 scheduled_tasks 在本迁移建好骨架，为 runs/sessions 的外键提供目标表；
业务接口分别在阶段 2、阶段 3 启用。

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from app.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind)

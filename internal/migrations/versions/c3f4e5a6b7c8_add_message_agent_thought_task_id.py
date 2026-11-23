"""add message_agent_thought.task_id (ask_user choice submission after history reload)

Revision ID: c3f4e5a6b7c8
Revises: bc23de45ef67
Create Date: 2026-09-01 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision = 'c3f4e5a6b7c8'
down_revision = 'bc23de45ef67'
branch_labels = None
depends_on = None


def upgrade():
    # message_agent_thought：任务ID（SSE 事件携带；历史回显后 ask_user 仍可提交选择）
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', PG_UUID(as_uuid=True), nullable=True))


def downgrade():
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.drop_column('task_id')

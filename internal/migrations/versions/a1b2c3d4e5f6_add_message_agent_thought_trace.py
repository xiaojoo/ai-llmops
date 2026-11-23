"""add message_agent_thought trace

Revision ID: a1b2c3d4e5f6
Revises: 7c9e1f2a3b4d
Create Date: 2026-08-26 02:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '7c9e1f2a3b4d'
branch_labels = None
depends_on = None


def upgrade():
    # message_agent_thought.agentic 重检轨迹
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade():
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.drop_column('trace')

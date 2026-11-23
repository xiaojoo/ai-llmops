"""add conversation dialog_round (short-term memory rounds per conversation)

Revision ID: bc23de45ef67
Revises: ab12cd34ef56
Create Date: 2026-09-01 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bc23de45ef67'
down_revision = 'ab12cd34ef56'
branch_labels = None
depends_on = None


def upgrade():
    # conversation：会话级短期记忆窗口轮数覆盖（NULL = 使用应用配置）
    with op.batch_alter_table('conversation', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dialog_round', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('conversation', schema=None) as batch_op:
        batch_op.drop_column('dialog_round')

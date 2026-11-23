"""add agent_thought model_name / llm_output / tool_calls

Revision ID: ab12cd34ef56
Revises: f3e9d2c1b4a5
Create Date: 2026-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'ab12cd34ef56'
down_revision = 'f3e9d2c1b4a5'
branch_labels = None
depends_on = None


def upgrade():
    # message_agent_thought：LLM 轨迹补全（LangSmith 风格：模型名 / 完整输出 / 工具调用声明）
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False))
        batch_op.add_column(sa.Column('llm_output', sa.Text(), server_default=sa.text("''::text"), nullable=False))
        batch_op.add_column(sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade():
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.drop_column('tool_calls')
        batch_op.drop_column('llm_output')
        batch_op.drop_column('model_name')

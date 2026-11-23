"""orchestrator subagent

Revision ID: b71440330486
Revises: 658dadf5c107
Create Date: 2026-08-25 08:16:54.533236

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b71440330486'
down_revision = '658dadf5c107'
branch_labels = None
depends_on = None


def upgrade():
    # App.app_type
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.add_column(sa.Column('app_type', sa.String(length=50), server_default=sa.text("'agent'::character varying"), nullable=False))
    # AppConfig / AppConfigVersion .orchestrator_config
    with op.batch_alter_table('app_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('orchestrator_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    with op.batch_alter_table('app_config_version', schema=None) as batch_op:
        batch_op.add_column(sa.Column('orchestrator_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    # message_agent_thought 子任务归属
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sub_task_id', postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column('sub_task_title', sa.Text(), server_default=sa.text("''::text"), nullable=False))
    # 新表 sub_task_checkpoint
    op.create_table('sub_task_checkpoint',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('app_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('query', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('title', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('role_prompt', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('expect_output', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('required_tools', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=50), server_default=sa.text("'running'::character varying"), nullable=False),
        sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('iteration_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('partial_answer', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('total_token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_price', sa.Numeric(10, 7), server_default=sa.text('0.0'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_sub_task_checkpoint_id'),
    )
    op.create_index('idx_sub_task_checkpoint_conv_pos', 'sub_task_checkpoint', ['conversation_id', 'position'])


def downgrade():
    op.drop_index('idx_sub_task_checkpoint_conv_pos', table_name='sub_task_checkpoint')
    op.drop_table('sub_task_checkpoint')
    with op.batch_alter_table('message_agent_thought', schema=None) as batch_op:
        batch_op.drop_column('sub_task_title')
        batch_op.drop_column('sub_task_id')
    with op.batch_alter_table('app_config_version', schema=None) as batch_op:
        batch_op.drop_column('orchestrator_config')
    with op.batch_alter_table('app_config', schema=None) as batch_op:
        batch_op.drop_column('orchestrator_config')
    with op.batch_alter_table('app', schema=None) as batch_op:
        batch_op.drop_column('app_type')

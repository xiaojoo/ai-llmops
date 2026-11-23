"""add agent_run table + sub_task_checkpoint.plan_id

Revision ID: ee11aa22bb33
Revises: b9a8d7c6e5f4
Create Date: 2026-09-08 09:00:00.000000

agent_run：Run 生命周期/统计持久化实体（message.status 收窄为最新 run 的投影）。
sub_task_checkpoint.plan_id：断点计划身份（replan/regenerate 重拆时旧断点失效，防错误复用）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision = 'ee11aa22bb33'
down_revision = 'b9a8d7c6e5f4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_run',
        sa.Column('id', PG_UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False, comment='主键ID（= run_id）'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False, comment='创建时间'),
        sa.Column('created_by', PG_UUID(as_uuid=True), nullable=False, comment='创建人ID（账号/终端用户）'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False, comment='更新时间'),
        sa.Column('updated_by', PG_UUID(as_uuid=True), nullable=False, comment='更新人ID'),
        sa.Column('app_id', PG_UUID(as_uuid=True), nullable=False, comment='关联应用ID'),
        sa.Column('conversation_id', PG_UUID(as_uuid=True), nullable=False, comment='所属会话ID'),
        sa.Column('message_id', PG_UUID(as_uuid=True), nullable=False, comment='所属消息ID'),
        sa.Column('parent_run_id', PG_UUID(as_uuid=True), sa.ForeignKey('agent_run.id'), nullable=True, comment='父 run_id（编排器主 run → 子任务 run）'),
        sa.Column('invoke_from', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False, comment='调用来源'),
        sa.Column('agent_type', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False, comment='Agent 类型'),
        sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='该消息第几次 run'),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'pending'::character varying"), nullable=False, comment='run 状态（RunStatus）'),
        sa.Column('error', sa.Text(), server_default=sa.text("''::text"), nullable=False, comment='错误信息'),
        sa.Column('resume_trigger', sa.Boolean(), nullable=True, comment='是否显式恢复触发'),
        sa.Column('total_token_count', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='总token数'),
        sa.Column('total_price', sa.Numeric(10, 7), server_default=sa.text('0.0'), nullable=False, comment='总费用'),
        sa.Column('latency', sa.Float(), server_default=sa.text('0.0'), nullable=False, comment='总耗时（秒）'),
        sa.Column('started_at', sa.DateTime(), nullable=True, comment='开始执行时间'),
        sa.Column('ended_at', sa.DateTime(), nullable=True, comment='结束时间'),
        sa.PrimaryKeyConstraint('id', name='pk_agent_run_id'),
        sa.UniqueConstraint('message_id', 'version', name='uq_agent_run_message_version'),
        comment='Agent 运行表（run 生命周期/统计）',
    )
    op.create_index('idx_agent_run_parent', 'agent_run', ['parent_run_id'])
    op.create_index('idx_agent_run_conversation', 'agent_run', ['conversation_id'])

    with op.batch_alter_table('sub_task_checkpoint', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'plan_id', PG_UUID(as_uuid=True), nullable=True,
            comment='计划身份（plan 代际；replan/regenerate 重拆时旧断点失效）',
        ))


def downgrade():
    with op.batch_alter_table('sub_task_checkpoint', schema=None) as batch_op:
        batch_op.drop_column('plan_id')

    op.drop_index('idx_agent_run_conversation', table_name='agent_run')
    op.drop_index('idx_agent_run_parent', table_name='agent_run')
    op.drop_table('agent_run')

"""add api_llm_model table (custom API LLM provider)

Revision ID: fe65dc34ba21
Revises: ee11aa22bb33
Create Date: 2026-09-08 22:41:55.752269

自定义 API 大语言模型表：用户按账号添加的 OpenAI/Anthropic/Responses 兼容模型。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'fe65dc34ba21'
down_revision = 'ee11aa22bb33'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_llm_model',
        sa.Column('id', PG_UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False, comment='创建时间'),
        sa.Column('created_by', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False, comment='创建人ID'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False, comment='更新时间'),
        sa.Column('updated_by', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False, comment='更新人ID'),
        sa.Column('account_id', PG_UUID(as_uuid=True), nullable=False, comment='归属账号ID'),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False, comment='展示名（模型选择器显示）'),
        sa.Column('protocol', sa.String(length=50), server_default=sa.text("''::character varying"), nullable=False, comment='协议：openai / responses / anthropic'),
        sa.Column('model_id', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False, comment='请求体 model 字段'),
        sa.Column('base_url', sa.String(length=500), server_default=sa.text("''::character varying"), nullable=False, comment='端点地址（可空）'),
        sa.Column('api_key', sa.Text(), server_default=sa.text("''::text"), nullable=False, comment='API Key（AES 加密存储）'),
        sa.Column('features', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False, comment='能力标记：tool_call/agent_thought/image_input'),
        sa.Column('context_window', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='上下文窗口长度'),
        sa.Column('max_output_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='最大输出 tokens'),
        sa.Column('remark', sa.Text(), server_default=sa.text("''::text"), nullable=False, comment='备注'),
        sa.Column('icon', sa.String(length=500), server_default=sa.text("''::character varying"), nullable=False, comment='图标URL'),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='逻辑删除标记'),
        sa.PrimaryKeyConstraint('id', name='pk_api_llm_model_id'),
        comment='自定义 API 大语言模型表',
    )


def downgrade():
    op.drop_table('api_llm_model')

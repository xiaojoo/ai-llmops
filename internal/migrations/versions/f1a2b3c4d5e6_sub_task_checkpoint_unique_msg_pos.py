"""sub_task_checkpoint unique (message_id, position) index

Revision ID: f1a2b3c4d5e6
Revises: fe65dc34ba21
Create Date: 2026-09-09 00:00:00.000000

断点定位键由 (conversation_id, position) 改为 (message_id, position)：

同一会话内多轮编排消息会各自保存断点，不会因共享 (conversation_id, position)
而互相覆盖 UPsert，导致先停止的任务断点丢失、「继续执行」无法出现。
归一到消息维度后，中断后按 message_id 即可精确续跑该轮任务。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'fe65dc34ba21'
branch_labels = None
depends_on = None


def upgrade():
    # 旧键 (conversation_id, position) → 新键 (message_id, position)
    op.drop_index('idx_sub_task_checkpoint_conv_pos', table_name='sub_task_checkpoint')
    op.create_index(
        'idx_sub_task_checkpoint_msg_pos', 'sub_task_checkpoint',
        ['message_id', 'position'], unique=True,
    )


def downgrade():
    op.drop_index('idx_sub_task_checkpoint_msg_pos', table_name='sub_task_checkpoint')
    op.create_index(
        'idx_sub_task_checkpoint_conv_pos', 'sub_task_checkpoint',
        ['conversation_id', 'position'], unique=True,
    )

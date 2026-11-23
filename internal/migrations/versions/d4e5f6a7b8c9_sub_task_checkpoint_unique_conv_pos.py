"""sub_task_checkpoint unique (conversation_id, position) index

Revision ID: d4e5f6a7b8c9
Revises: b71440330486
Create Date: 2026-08-25 21:10:00.000000

I6: 断点定位键 (conversation_id, position) 由非唯一索引改为唯一索引，
支撑 save_checkpoint 的原子 upsert（ON CONFLICT），消除并发 get-then-create 竞态
导致的重复行与 get_checkpoint 的 MultipleResultsFound 崩溃。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'b71440330486'
branch_labels = None
depends_on = None


def upgrade():
    # 同名重建为唯一索引（表为空/无重复数据，直接替换）
    op.drop_index('idx_sub_task_checkpoint_conv_pos', table_name='sub_task_checkpoint')
    op.create_index(
        'idx_sub_task_checkpoint_conv_pos', 'sub_task_checkpoint',
        ['conversation_id', 'position'], unique=True,
    )


def downgrade():
    # 还原为非唯一索引
    op.drop_index('idx_sub_task_checkpoint_conv_pos', table_name='sub_task_checkpoint')
    op.create_index(
        'idx_sub_task_checkpoint_conv_pos', 'sub_task_checkpoint',
        ['conversation_id', 'position'],
    )

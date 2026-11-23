"""baseline schema (adopt existing DB state)

Revision ID: 273f811b2cf4
Revises:
Create Date: 2026-08-24 04:52:00.000000

本迁移是迁移链基线标记：数据库 alembic_version 指向 273f811b2cf4，
但仓库 internal/migrations/versions/ 此前为空（从未提交过任何版本文件）。
该 revision 来自外部环境（DB 由外部迁移/建表后 stamp），本仓库没有其文件。
为使 flask-migrate 链与 DB 状态一致，这里将 273f811b2cf4 物化为 no-op 基线：
upgrade/downgrade 均不执行任何操作，仅代表"数据库当前 schema 即基线状态"。
后续 autogenerate 迁移（如 add message is_archived）将以此 revision 为父节点。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '273f811b2cf4'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

"""PDF support: scan_history.page (page of the PDF where the code was found)

Revision ID: b5d1e8a2c907
Revises: a3f9c2d71b04
Create Date: 2026-11-19 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5d1e8a2c907'
down_revision = 'a3f9c2d71b04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scan_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('page', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('scan_history', schema=None) as batch_op:
        batch_op.drop_column('page')

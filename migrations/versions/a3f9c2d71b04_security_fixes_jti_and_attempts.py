"""Security fixes: token.jti (session revocation) and user.verification_attempts

Revision ID: a3f9c2d71b04
Revises: 7e2fd18e1136
Create Date: 2026-10-19 18:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f9c2d71b04'
down_revision = '7e2fd18e1136'
branch_labels = None
depends_on = None


def upgrade():
    # Old sessions have no jti and can't be revoked: remove them (users just log in again)
    op.execute('DELETE FROM token')

    with op.batch_alter_table('token', schema=None) as batch_op:
        batch_op.add_column(sa.Column('jti', sa.String(length=36), nullable=True))
        batch_op.create_index('ix_token_jti', ['jti'], unique=True)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verification_attempts', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('verification_attempts')

    with op.batch_alter_table('token', schema=None) as batch_op:
        batch_op.drop_index('ix_token_jti')
        batch_op.drop_column('jti')

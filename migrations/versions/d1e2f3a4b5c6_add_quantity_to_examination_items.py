"""add quantity to examination items

Revision ID: d1e2f3a4b5c6
Revises: e3f4a5b6c1d2
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'e3f4a5b6c1d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('examination_analyses',
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('examination_analysis_tools',
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    op.drop_column('examination_analyses', 'quantity')
    op.drop_column('examination_analysis_tools', 'quantity')

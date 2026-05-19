"""add_examination_analysis_tools

Revision ID: e3f4a5b6c1d2
Revises: c1d2e3f4a5b6
Create Date: 2026-05-19 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e3f4a5b6c1d2'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'examination_analysis_tools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('examination_id', sa.Integer(), nullable=False),
        sa.Column('tool_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('is_insurance', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['examination_id'], ['examinations.id']),
        sa.ForeignKeyConstraint(['tool_id'], ['analysis_tools.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('examination_analysis_tools')

"""direction many_to_many analyses

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-06-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e7f8a9b0c1d2'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'direction_analyses',
        sa.Column('direction_id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['direction_id'], ['doctor_directions.id']),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('direction_id', 'analysis_id'),
    )


def downgrade():
    op.drop_table('direction_analyses')

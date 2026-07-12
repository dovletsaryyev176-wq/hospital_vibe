"""add doctor direction categories

Revision ID: c9d0e1f2a3b4
Revises: e7f8a9b0c1d2
Create Date: 2026-07-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'doctor_direction_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column('doctor_directions',
        sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_doctor_directions_category_id',
        'doctor_directions', 'doctor_direction_categories',
        ['category_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_doctor_directions_category_id', 'doctor_directions', type_='foreignkey')
    op.drop_column('doctor_directions', 'category_id')
    op.drop_table('doctor_direction_categories')

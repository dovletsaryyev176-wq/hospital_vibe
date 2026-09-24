"""add doctor-direction category to analyses

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


_FK = 'fk_analyses_category_id'
_IX = 'ix_analyses_category_id'


def upgrade():
    # Existing analyses stay without a category until one is picked for them.
    op.add_column('analyses', sa.Column('category_id', sa.Integer(), nullable=True))
    # Index before the key: MySQL reuses it for the foreign key instead of
    # silently adding a second one of its own.
    op.create_index(_IX, 'analyses', ['category_id'])
    op.create_foreign_key(_FK, 'analyses', 'doctor_direction_categories',
                          ['category_id'], ['id'])


def downgrade():
    op.drop_constraint(_FK, 'analyses', type_='foreignkey')
    op.drop_index(_IX, table_name='analyses')
    op.drop_column('analyses', 'category_id')

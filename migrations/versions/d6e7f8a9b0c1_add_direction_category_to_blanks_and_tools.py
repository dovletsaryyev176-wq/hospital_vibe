"""add doctor-direction category to blanks and analysis tools

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


revision = 'd6e7f8a9b0c1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


# (table, column) — tools keep their own category_id / subcategory_id; the
# doctor-direction category is a second, separate column there.
_COLUMNS = (
    ('blanks', 'category_id'),
    ('analysis_tools', 'direction_category_id'),
)


def upgrade():
    # Existing rows stay without a category until one is picked for them.
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        # Index before the key: MySQL reuses it for the foreign key instead of
        # silently adding a second one of its own.
        op.create_index(f'ix_{table}_{column}', table, [column])
        op.create_foreign_key(f'fk_{table}_{column}', table, 'doctor_direction_categories',
                              [column], ['id'])


def downgrade():
    for table, column in _COLUMNS:
        op.drop_constraint(f'fk_{table}_{column}', table, type_='foreignkey')
        op.drop_index(f'ix_{table}_{column}', table_name=table)
        op.drop_column(table, column)

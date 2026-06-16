"""make analysis_tool_subcategories.category_id required

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-06-16

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None

FALLBACK_CATEGORY_NAME = 'Kategoriýasyz'


def upgrade():
    bind = op.get_bind()

    orphan_count = bind.execute(
        sa.text('SELECT COUNT(*) FROM analysis_tool_subcategories WHERE category_id IS NULL')
    ).scalar()

    if orphan_count:
        fallback_id = bind.execute(
            sa.text('SELECT id FROM analysis_tool_categories WHERE name = :name'),
            {'name': FALLBACK_CATEGORY_NAME},
        ).scalar()

        if fallback_id is None:
            result = bind.execute(
                sa.text(
                    'INSERT INTO analysis_tool_categories (name, is_active, created_at) '
                    'VALUES (:name, 1, NOW())'
                ),
                {'name': FALLBACK_CATEGORY_NAME},
            )
            fallback_id = result.lastrowid

        bind.execute(
            sa.text(
                'UPDATE analysis_tool_subcategories SET category_id = :cid '
                'WHERE category_id IS NULL'
            ),
            {'cid': fallback_id},
        )

    op.alter_column(
        'analysis_tool_subcategories', 'category_id',
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        'analysis_tool_subcategories', 'category_id',
        existing_type=sa.Integer(),
        nullable=True,
    )

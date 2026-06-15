"""add analysis tool categories and subcategories

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-06-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analysis_tool_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'analysis_tool_subcategories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['analysis_tool_categories.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('analysis_tools',
        sa.Column('category_id', sa.Integer(), nullable=True))
    op.add_column('analysis_tools',
        sa.Column('subcategory_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_analysis_tools_category_id',
        'analysis_tools', 'analysis_tool_categories',
        ['category_id'], ['id'],
    )
    op.create_foreign_key(
        'fk_analysis_tools_subcategory_id',
        'analysis_tools', 'analysis_tool_subcategories',
        ['subcategory_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_analysis_tools_subcategory_id', 'analysis_tools', type_='foreignkey')
    op.drop_constraint('fk_analysis_tools_category_id', 'analysis_tools', type_='foreignkey')
    op.drop_column('analysis_tools', 'subcategory_id')
    op.drop_column('analysis_tools', 'category_id')
    op.drop_table('analysis_tool_subcategories')
    op.drop_table('analysis_tool_categories')

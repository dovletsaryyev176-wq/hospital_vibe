"""analysis_tool many_to_many analyses

Revision ID: f1a2b3c4d5e6
Revises: d1e2f3a4b5c6
Create Date: 2026-06-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analysis_tool_analyses',
        sa.Column('tool_id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tool_id'], ['analysis_tools.id']),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('tool_id', 'analysis_id'),
    )

    # Migrate existing single-analysis data into junction table
    op.execute(
        'INSERT INTO analysis_tool_analyses (tool_id, analysis_id) '
        'SELECT id, analysis_id FROM analysis_tools'
    )

    op.drop_constraint(
        'analysis_tools_ibfk_1',
        'analysis_tools',
        type_='foreignkey',
    )
    op.drop_column('analysis_tools', 'analysis_id')


def downgrade():
    op.add_column(
        'analysis_tools',
        sa.Column('analysis_id', sa.Integer(), nullable=True),
    )

    # Restore first analysis for each tool
    op.execute(
        'UPDATE analysis_tools t SET analysis_id = ('
        '  SELECT analysis_id FROM analysis_tool_analyses a'
        '  WHERE a.tool_id = t.id LIMIT 1'
        ')'
    )

    op.alter_column('analysis_tools', 'analysis_id', nullable=False)

    op.create_foreign_key(
        'analysis_tools_analysis_id_fkey',
        'analysis_tools', 'analyses',
        ['analysis_id'], ['id'],
    )

    op.drop_table('analysis_tool_analyses')

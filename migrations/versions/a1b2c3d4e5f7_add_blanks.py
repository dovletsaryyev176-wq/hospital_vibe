"""add blanks

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'blanks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_insurance', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('total_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'blank_analyses',
        sa.Column('blank_id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['blank_id'], ['blanks.id']),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id']),
        sa.PrimaryKeyConstraint('blank_id', 'analysis_id'),
    )

    op.create_table(
        'examination_blanks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('examination_id', sa.Integer(), nullable=False),
        sa.Column('blank_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('is_insurance', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['examination_id'], ['examinations.id']),
        sa.ForeignKeyConstraint(['blank_id'], ['blanks.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('examination_blanks')
    op.drop_table('blank_analyses')
    op.drop_table('blanks')

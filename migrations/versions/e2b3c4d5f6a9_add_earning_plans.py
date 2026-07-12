"""add earning_plans table

Revision ID: e2b3c4d5f6a9
Revises: d1a2b3c4e5f8
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa

revision = 'e2b3c4d5f6a9'
down_revision = 'd1a2b3c4e5f8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'earning_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'year', 'month', name='uq_earning_plan_user_month'),
    )


def downgrade():
    op.drop_table('earning_plans')

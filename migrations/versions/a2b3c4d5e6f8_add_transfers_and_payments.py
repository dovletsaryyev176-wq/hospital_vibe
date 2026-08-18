"""add department transfers and the payment log to inpatient stays

Revision ID: a2b3c4d5e6f8
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f8'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalization_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('from_department_id', sa.Integer(), nullable=False),
        sa.Column('to_department_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('transferred_at', sa.DateTime(), nullable=False),
        sa.Column('transferred_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id']),
        sa.ForeignKeyConstraint(['from_department_id'], ['departments.id']),
        sa.ForeignKeyConstraint(['to_department_id'], ['departments.id']),
        sa.ForeignKeyConstraint(['transferred_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_hospitalization_transfers_hospitalization_id'),
                    'hospitalization_transfers', ['hospitalization_id'])

    # Payments taken before this table existed are not reconstructed: a stay
    # keeps its `paid_total`, and the page prints that as one undetailed row.
    # Splitting it into cash and terminal after the fact is not possible — the
    # bed and meal days it covered have grown since.
    op.create_table(
        'hospitalization_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('cash_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('terminal_amount', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('paid_at', sa.DateTime(), nullable=False),
        sa.Column('paid_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id']),
        sa.ForeignKeyConstraint(['paid_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_hospitalization_payments_hospitalization_id'),
                    'hospitalization_payments', ['hospitalization_id'])
    op.create_index(op.f('ix_hospitalization_payments_paid_at'),
                    'hospitalization_payments', ['paid_at'])


def downgrade():
    op.drop_index(op.f('ix_hospitalization_payments_paid_at'),
                  table_name='hospitalization_payments')
    op.drop_index(op.f('ix_hospitalization_payments_hospitalization_id'),
                  table_name='hospitalization_payments')
    op.drop_table('hospitalization_payments')

    op.drop_index(op.f('ix_hospitalization_transfers_hospitalization_id'),
                  table_name='hospitalization_transfers')
    op.drop_table('hospitalization_transfers')

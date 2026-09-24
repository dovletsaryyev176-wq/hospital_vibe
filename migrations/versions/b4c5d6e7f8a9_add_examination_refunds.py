"""add examination refunds

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f8
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a2b3c4d5e6f8'
branch_labels = None
depends_on = None


# Every table holding one paid line of an examination. A refunded line points
# at the refund it was given back in and keeps what was returned for it.
_LINE_TABLES = (
    'examination_analyses',
    'examination_analysis_tools',
    'examination_blanks',
    'examination_directions',
)


def _fk_name(table):
    return f'fk_{table}_refund_id'


def upgrade():
    op.create_table(
        'examination_refunds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('examination_id', sa.Integer(), nullable=False),
        sa.Column('refunded_at', sa.DateTime(), nullable=False),
        sa.Column('refunded_by_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(['examination_id'], ['examinations.id'],
                                name='fk_examination_refunds_examination_id'),
        sa.ForeignKeyConstraint(['refunded_by_id'], ['users.id'],
                                name='fk_examination_refunds_refunded_by_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    # examination_id needs no index of its own: MySQL indexes a foreign key.
    op.create_index('ix_examination_refunds_refunded_at', 'examination_refunds',
                    ['refunded_at'])

    for table in _LINE_TABLES:
        op.add_column(table, sa.Column('refund_id', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('refund_amount', sa.Numeric(10, 2), nullable=True))
        op.add_column(table, sa.Column('refund_discount', sa.Numeric(10, 2), nullable=True))
        # Index before the key: MySQL reuses it for the foreign key instead of
        # silently adding a second one of its own.
        op.create_index(f'ix_{table}_refund_id', table, ['refund_id'])
        op.create_foreign_key(_fk_name(table), table, 'examination_refunds',
                              ['refund_id'], ['id'])


def downgrade():
    for table in _LINE_TABLES:
        op.drop_constraint(_fk_name(table), table, type_='foreignkey')
        op.drop_index(f'ix_{table}_refund_id', table_name=table)
        op.drop_column(table, 'refund_discount')
        op.drop_column(table, 'refund_amount')
        op.drop_column(table, 'refund_id')

    op.drop_index('ix_examination_refunds_refunded_at', table_name='examination_refunds')
    op.drop_table('examination_refunds')

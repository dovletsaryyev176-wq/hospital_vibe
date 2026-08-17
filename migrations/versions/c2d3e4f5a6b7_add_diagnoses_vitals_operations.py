"""add diagnoses, vital records, operations and discharge summary

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-17 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    # ── discharge summary on the stay itself ─────────────────────────────────
    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('outcome', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('epicrisis', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('recommendations', sa.Text(), nullable=True))

    # ── diagnoses ────────────────────────────────────────────────────────────
    op.create_table(
        'hospitalization_diagnoses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_diagnoses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_diagnoses_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_diagnoses_kind'),
                              ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_diagnoses_author_id'),
                              ['author_id'], unique=False)

    # ── nurse's temperature sheet ────────────────────────────────────────────
    op.create_table(
        'hospitalization_vital_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('measured_at', sa.DateTime(), nullable=False),
        sa.Column('temperature', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('pulse', sa.Integer(), nullable=True),
        sa.Column('systolic', sa.Integer(), nullable=True),
        sa.Column('diastolic', sa.Integer(), nullable=True),
        sa.Column('respiratory_rate', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('recorded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_vital_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_vital_records_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_vital_records_measured_at'),
                              ['measured_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_vital_records_recorded_by_id'),
                              ['recorded_by_id'], unique=False)

    # ── operation catalogue ──────────────────────────────────────────────────
    op.create_table(
        'operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # ── operations on a stay ─────────────────────────────────────────────────
    op.create_table(
        'hospitalization_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('operation_id', sa.Integer(), nullable=False),
        sa.Column('surgeon_id', sa.Integer(), nullable=False),
        sa.Column('anesthesiologist_id', sa.Integer(), nullable=True),
        sa.Column('anesthesia', sa.String(length=20), nullable=False),
        sa.Column('planned_at', sa.DateTime(), nullable=True),
        sa.Column('performed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('indication', sa.String(length=500), nullable=True),
        sa.Column('protocol', sa.Text(), nullable=True),
        sa.Column('complications', sa.String(length=500), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('performed_by_id', sa.Integer(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ),
        sa.ForeignKeyConstraint(['surgeon_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['anesthesiologist_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['performed_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_operations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_operations_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_operations_operation_id'),
                              ['operation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_operations_surgeon_id'),
                              ['surgeon_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_operations_status'),
                              ['status'], unique=False)

    op.create_table(
        'hospitalization_operation_assistants',
        sa.Column('operation_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['operation_id'], ['hospitalization_operations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('operation_id', 'user_id'),
    )


def downgrade():
    op.drop_table('hospitalization_operation_assistants')

    with op.batch_alter_table('hospitalization_operations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hospitalization_operations_status'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_operations_surgeon_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_operations_operation_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_operations_hospitalization_id'))
    op.drop_table('hospitalization_operations')

    op.drop_table('operations')

    with op.batch_alter_table('hospitalization_vital_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hospitalization_vital_records_recorded_by_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_vital_records_measured_at'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_vital_records_hospitalization_id'))
    op.drop_table('hospitalization_vital_records')

    with op.batch_alter_table('hospitalization_diagnoses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hospitalization_diagnoses_author_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_diagnoses_kind'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_diagnoses_hospitalization_id'))
    op.drop_table('hospitalization_diagnoses')

    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.drop_column('recommendations')
        batch_op.drop_column('epicrisis')
        batch_op.drop_column('outcome')

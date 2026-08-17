"""add hospitalizations and relatives

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('history_number', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('admitted_at', sa.DateTime(), nullable=False),
        sa.Column('admitted_by_id', sa.Integer(), nullable=False),
        sa.Column('discharged_at', sa.DateTime(), nullable=True),
        sa.Column('discharged_by_id', sa.Integer(), nullable=True),
        sa.Column('room_id', sa.Integer(), nullable=True),
        sa.Column('bed_id', sa.Integer(), nullable=True),
        sa.Column('bed_assigned_at', sa.DateTime(), nullable=True),
        sa.Column('bed_assigned_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['admitted_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['discharged_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
        sa.ForeignKeyConstraint(['bed_id'], ['beds.id'], ),
        sa.ForeignKeyConstraint(['bed_assigned_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalizations_patient_id'), ['patient_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalizations_department_id'), ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalizations_history_number'), ['history_number'], unique=True)
        batch_op.create_index(batch_op.f('ix_hospitalizations_status'), ['status'], unique=False)

    op.create_table(
        'hospitalization_relatives',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('relation', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_relatives', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_relatives_hospitalization_id'),
                              ['hospitalization_id'], unique=False)


def downgrade():
    op.drop_table('hospitalization_relatives')

    op.drop_table('hospitalizations')

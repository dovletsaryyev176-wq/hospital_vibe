"""add attending doctor to hospitalizations

Revision ID: e5f6a7b8c9d1
Revises: c0d1e2f3a4b5
Create Date: 2026-08-16 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d1'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalization_doctor_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['doctor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_doctor_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_doctor_assignments_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_doctor_assignments_doctor_id'),
                              ['doctor_id'], unique=False)

    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('doctor_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('doctor_assigned_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('doctor_assigned_by_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_hospitalizations_doctor_id'), ['doctor_id'], unique=False)
        batch_op.create_foreign_key('fk_hospitalizations_doctor_id_users', 'users', ['doctor_id'], ['id'])
        batch_op.create_foreign_key('fk_hospitalizations_doctor_assigned_by_id_users', 'users',
                                    ['doctor_assigned_by_id'], ['id'])


def downgrade():
    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_hospitalizations_doctor_assigned_by_id_users', type_='foreignkey')
        batch_op.drop_constraint('fk_hospitalizations_doctor_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_hospitalizations_doctor_id'))
        batch_op.drop_column('doctor_assigned_by_id')
        batch_op.drop_column('doctor_assigned_at')
        batch_op.drop_column('doctor_id')

    with op.batch_alter_table('hospitalization_doctor_assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hospitalization_doctor_assignments_doctor_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_doctor_assignments_hospitalization_id'))
    op.drop_table('hospitalization_doctor_assignments')

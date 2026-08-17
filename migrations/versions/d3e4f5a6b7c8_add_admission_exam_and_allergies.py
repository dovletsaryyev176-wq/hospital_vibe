"""add admission examination and patient allergies

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-17 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    # ── allergy review stamp on the patient ──────────────────────────────────
    # nullable on purpose: every existing patient starts as "not asked", which
    # is exactly what they are
    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allergies_reviewed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('allergies_reviewed_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_patients_allergies_reviewed_by',
                                    'users', ['allergies_reviewed_by_id'], ['id'])

    op.create_table(
        'patient_allergies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('substance', sa.String(length=200), nullable=False),
        sa.Column('reaction', sa.String(length=500), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('recorded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('removed_at', sa.DateTime(), nullable=True),
        sa.Column('removed_by_id', sa.Integer(), nullable=True),
        sa.Column('remove_reason', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['removed_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('patient_allergies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_patient_allergies_patient_id'),
                              ['patient_id'], unique=False)

    # ── admission examination ────────────────────────────────────────────────
    op.create_table(
        'hospitalization_admission_exams',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('complaints', sa.Text(), nullable=False),
        sa.Column('anamnesis_morbi', sa.Text(), nullable=False),
        sa.Column('anamnesis_vitae', sa.Text(), nullable=True),
        sa.Column('objective_status', sa.Text(), nullable=False),
        sa.Column('local_status', sa.Text(), nullable=True),
        sa.Column('diagnosis_rationale', sa.Text(), nullable=True),
        sa.Column('examination_plan', sa.Text(), nullable=True),
        sa.Column('treatment_plan', sa.Text(), nullable=True),
        sa.Column('temperature', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('pulse', sa.Integer(), nullable=True),
        sa.Column('systolic', sa.Integer(), nullable=True),
        sa.Column('diastolic', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('weight', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hospitalization_id', name='uq_admission_exam_hospitalization'),
    )
    with op.batch_alter_table('hospitalization_admission_exams', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_admission_exams_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_admission_exams_author_id'),
                              ['author_id'], unique=False)


def downgrade():
    with op.batch_alter_table('hospitalization_admission_exams', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hospitalization_admission_exams_author_id'))
        batch_op.drop_index(batch_op.f('ix_hospitalization_admission_exams_hospitalization_id'))
    op.drop_table('hospitalization_admission_exams')

    with op.batch_alter_table('patient_allergies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_patient_allergies_patient_id'))
    op.drop_table('patient_allergies')

    with op.batch_alter_table('patients', schema=None) as batch_op:
        batch_op.drop_constraint('fk_patients_allergies_reviewed_by', type_='foreignkey')
        batch_op.drop_column('allergies_reviewed_by_id')
        batch_op.drop_column('allergies_reviewed_at')

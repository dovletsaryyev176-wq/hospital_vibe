"""snapshot prices and patient history

Revision ID: a1b2c3d4e5f6
Revises: 96568e6a7ae1
Create Date: 2026-05-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'a1b2c3d4e5f6'
down_revision = '96568e6a7ae1'
branch_labels = None
depends_on = None


def upgrade():
    # Drop responsible_id from combined_analyses if it exists (orphaned column)
    bind = op.get_bind()
    insp = inspect(bind)
    ca_cols = [c['name'] for c in insp.get_columns('combined_analyses')]
    if 'responsible_id' in ca_cols:
        with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
            batch_op.drop_column('responsible_id')

    with op.batch_alter_table('examination_analyses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('is_insurance', sa.Boolean(), nullable=True))

    with op.batch_alter_table('examination_directions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price', sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column('is_insurance', sa.Boolean(), nullable=True))

    with op.batch_alter_table('examinations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('patient_has_insurance', sa.Boolean(), nullable=True))

    # Backfill: snapshot current price/insurance from analyses and directions
    op.execute("""
        UPDATE examination_analyses ea
        JOIN analyses a ON a.id = ea.analysis_id
        SET ea.price = a.price, ea.is_insurance = a.is_insurance
    """)

    op.execute("""
        UPDATE examination_directions ed
        JOIN doctor_directions d ON d.id = ed.direction_id
        SET ed.price = d.price, ed.is_insurance = d.is_insurance
    """)

    op.execute("""
        UPDATE examinations e
        JOIN patients p ON p.id = e.patient_id
        SET e.patient_has_insurance = (
            p.insurance_number IS NOT NULL AND p.insurance_number != ''
        )
    """)


def downgrade():
    with op.batch_alter_table('examinations', schema=None) as batch_op:
        batch_op.drop_column('patient_has_insurance')

    with op.batch_alter_table('examination_directions', schema=None) as batch_op:
        batch_op.drop_column('is_insurance')
        batch_op.drop_column('price')

    with op.batch_alter_table('examination_analyses', schema=None) as batch_op:
        batch_op.drop_column('is_insurance')
        batch_op.drop_column('price')

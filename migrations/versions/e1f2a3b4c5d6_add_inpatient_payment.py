"""add cashier payment to hospitalizations

Revision ID: e1f2a3b4c5d6
Revises: a906fb65b85f
Create Date: 2026-08-18

"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'a906fb65b85f'
branch_labels = None
depends_on = None


# Every table holding one charge line of a stay — the cashier records cash or
# terminal per line, exactly as the outpatient section does.
_LINE_TABLES = (
    'hospitalization_bed_stays',
    'hospitalization_meal_assignments',
    'hospitalization_medication_dispenses',
    'hospitalization_analysis_orders',
    'hospitalization_tool_orders',
    'hospitalization_blank_orders',
    'hospitalization_consultations',
    'hospitalization_operations',
)


def _paid_by_fk_name():
    """Name MySQL gave the unnamed foreign key on hospitalizations.paid_by_id."""
    for fk in sa.inspect(op.get_bind()).get_foreign_keys('hospitalizations'):
        if fk['constrained_columns'] == ['paid_by_id']:
            return fk['name']
    return None


def upgrade():
    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('patient_has_insurance', sa.Boolean(),
                                      nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('is_paid', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('paid_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('paid_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('paid_total', sa.Numeric(10, 2), nullable=True))
        batch_op.create_foreign_key(None, 'users', ['paid_by_id'], ['id'])

    # Insurance follows the patient's card, the same rule the outpatient
    # section applies when an examination is opened. Stays that already exist
    # were admitted before the flag existed — read it off the card now.
    op.execute("""
        UPDATE hospitalizations h
        JOIN patients p ON p.id = h.patient_id
        SET h.patient_has_insurance = (p.insurance_number IS NOT NULL
                                       AND p.insurance_number <> '')
    """)

    for table in _LINE_TABLES:
        op.add_column(table,
            sa.Column('payment_method', sa.String(length=10), nullable=True))


def downgrade():
    for table in _LINE_TABLES:
        op.drop_column(table, 'payment_method')

    # The foreign key above was created without a name, so MySQL named it
    # itself; look the real name up instead of guessing.
    name = _paid_by_fk_name()
    if name:
        op.drop_constraint(name, 'hospitalizations', type_='foreignkey')

    with op.batch_alter_table('hospitalizations', schema=None) as batch_op:
        batch_op.drop_column('paid_total')
        batch_op.drop_column('paid_by_id')
        batch_op.drop_column('paid_at')
        batch_op.drop_column('is_paid')
        batch_op.drop_column('patient_has_insurance')

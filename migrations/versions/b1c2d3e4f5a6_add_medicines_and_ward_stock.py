"""add medicines, ward stock and medication orders

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f4
Create Date: 2026-08-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a7b8c9d0e1f4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'medicines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'department_medicine_stocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('medicine_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['medicine_id'], ['medicines.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('department_id', 'medicine_id', name='uq_department_medicine'),
    )
    with op.batch_alter_table('department_medicine_stocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_department_medicine_stocks_department_id'),
                              ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_department_medicine_stocks_medicine_id'),
                              ['medicine_id'], unique=False)

    op.create_table(
        'hospitalization_medication_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('medicine_id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('dose', sa.String(length=100), nullable=False),
        sa.Column('route', sa.String(length=20), nullable=False),
        sa.Column('frequency', sa.String(length=100), nullable=True),
        sa.Column('quantity_per_dose', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('planned_end_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stopped_at', sa.DateTime(), nullable=True),
        sa.Column('stopped_by_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['medicine_id'], ['medicines.id'], ),
        sa.ForeignKeyConstraint(['doctor_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['stopped_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_medication_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_orders_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_orders_medicine_id'),
                              ['medicine_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_orders_doctor_id'),
                              ['doctor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_orders_status'),
                              ['status'], unique=False)

    op.create_table(
        'hospitalization_medication_dispenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('medicine_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('given_at', sa.DateTime(), nullable=False),
        sa.Column('given_by_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['hospitalization_medication_orders.id'], ),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['medicine_id'], ['medicines.id'], ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['given_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_medication_dispenses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_dispenses_order_id'),
                              ['order_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_dispenses_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_dispenses_medicine_id'),
                              ['medicine_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_medication_dispenses_department_id'),
                              ['department_id'], unique=False)

    op.create_table(
        'medicine_stock_movements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('medicine_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('balance_after', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('dispense_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['medicine_id'], ['medicines.id'], ),
        sa.ForeignKeyConstraint(['dispense_id'], ['hospitalization_medication_dispenses.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('medicine_stock_movements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_medicine_stock_movements_department_id'),
                              ['department_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_medicine_stock_movements_medicine_id'),
                              ['medicine_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_medicine_stock_movements_dispense_id'),
                              ['dispense_id'], unique=False)


def downgrade():
    op.drop_table('medicine_stock_movements')

    op.drop_table('hospitalization_medication_dispenses')

    op.drop_table('hospitalization_medication_orders')

    op.drop_table('department_medicine_stocks')

    op.drop_table('medicines')

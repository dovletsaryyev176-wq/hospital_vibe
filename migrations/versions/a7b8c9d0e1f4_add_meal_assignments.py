"""add hospitalization meal assignments

Revision ID: a7b8c9d0e1f4
Revises: f6a7b8c9d0e2
Create Date: 2026-08-16 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f4'
down_revision = 'f6a7b8c9d0e2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalization_meal_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('meal_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_by_id', sa.Integer(), nullable=False),
        sa.Column('ended_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['meal_id'], ['meals.id'], ),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['ended_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_meal_assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_meal_assignments_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_meal_assignments_meal_id'),
                              ['meal_id'], unique=False)


def downgrade():
    op.drop_table('hospitalization_meal_assignments')

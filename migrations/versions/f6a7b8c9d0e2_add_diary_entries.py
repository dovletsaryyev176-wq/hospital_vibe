"""add hospitalization diary entries

Revision ID: f6a7b8c9d0e2
Revises: e5f6a7b8c9d1
Create Date: 2026-08-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e2'
down_revision = 'e5f6a7b8c9d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalization_diary_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('complaints', sa.Text(), nullable=True),
        sa.Column('objective', sa.Text(), nullable=True),
        sa.Column('dynamics', sa.Text(), nullable=True),
        sa.Column('plan', sa.Text(), nullable=True),
        sa.Column('temperature', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('blood_pressure', sa.String(length=20), nullable=True),
        sa.Column('pulse', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_diary_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_diary_entries_hospitalization_id'),
                              ['hospitalization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_hospitalization_diary_entries_author_id'),
                              ['author_id'], unique=False)


def downgrade():
    op.drop_table('hospitalization_diary_entries')

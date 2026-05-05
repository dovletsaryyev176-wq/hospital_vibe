"""add_responsible_to_combined_analyses

Revision ID: 72058c90ae8a
Revises: 96568e6a7ae1
Create Date: 2026-05-05 15:13:52.069192

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72058c90ae8a'
down_revision = '96568e6a7ae1'
branch_labels = None
depends_on = None


def upgrade():
    # Add column as nullable first so existing rows don't violate NOT NULL
    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('responsible_id', sa.Integer(), nullable=True))

    # Backfill existing rows with the first available user id
    conn = op.get_bind()
    result = conn.execute(sa.text('SELECT id FROM users LIMIT 1'))
    row = result.fetchone()
    if row:
        conn.execute(
            sa.text('UPDATE combined_analyses SET responsible_id = :uid WHERE responsible_id IS NULL'),
            {'uid': row[0]},
        )

    # Now apply NOT NULL + FK
    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.alter_column('responsible_id', nullable=False)
        batch_op.create_foreign_key(None, 'users', ['responsible_id'], ['id'])


def downgrade():
    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_column('responsible_id')

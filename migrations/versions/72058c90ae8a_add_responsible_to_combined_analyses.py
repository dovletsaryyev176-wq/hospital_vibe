"""add_responsible_to_combined_analyses

Revision ID: 72058c90ae8a
Revises: 96568e6a7ae1
Create Date: 2026-05-05 15:13:52.069192

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '72058c90ae8a'
down_revision = '96568e6a7ae1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns('combined_analyses')]
    if 'responsible_id' in cols:
        return

    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('responsible_id', sa.Integer(), nullable=True))

    conn = op.get_bind()
    result = conn.execute(sa.text('SELECT id FROM users LIMIT 1'))
    row = result.fetchone()
    if row:
        conn.execute(
            sa.text('UPDATE combined_analyses SET responsible_id = :uid WHERE responsible_id IS NULL'),
            {'uid': row[0]},
        )

    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.alter_column('responsible_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            'fk_combined_analyses_responsible', 'users', ['responsible_id'], ['id']
        )


def downgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns('combined_analyses')]
    if 'responsible_id' not in cols:
        return

    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_combined_analyses_responsible', type_='foreignkey')
        batch_op.drop_column('responsible_id')

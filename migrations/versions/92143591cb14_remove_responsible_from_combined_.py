"""remove_responsible_from_combined_analyses

Revision ID: 92143591cb14
Revises: 72058c90ae8a
Create Date: 2026-05-05 15:18:53.630567

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
revision = '92143591cb14'
down_revision = '72058c90ae8a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns('combined_analyses')]
    if 'responsible_id' not in cols:
        return

    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        fks = insp.get_foreign_keys('combined_analyses')
        fk_names = [fk['name'] for fk in fks if 'responsible_id' in fk.get('constrained_columns', [])]
        for fk_name in fk_names:
            if fk_name:
                batch_op.drop_constraint(fk_name, type_='foreignkey')
        batch_op.drop_column('responsible_id')


def downgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns('combined_analyses')]
    if 'responsible_id' in cols:
        return

    with op.batch_alter_table('combined_analyses', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('responsible_id', sa.Integer(), nullable=False)
        )
        batch_op.create_foreign_key(
            'fk_combined_analyses_responsible', 'users', ['responsible_id'], ['id']
        )

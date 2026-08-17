"""add hospitalization bed stays

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-08-16 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c0d1e2f3a4b5'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hospitalization_bed_stays',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hospitalization_id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('bed_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_insurance', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hospitalization_id'], ['hospitalizations.id'], ),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
        sa.ForeignKeyConstraint(['bed_id'], ['beds.id'], ),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('hospitalization_bed_stays', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hospitalization_bed_stays_hospitalization_id'),
                              ['hospitalization_id'], unique=False)

    # Backfill: any stay that already has a bed becomes its first period.
    conn = op.get_bind()
    rows = conn.execute(sa.text("""
        SELECT h.id, h.room_id, h.bed_id, h.bed_assigned_at, h.admitted_at,
               h.discharged_at, h.bed_assigned_by_id, h.admitted_by_id,
               b.price, b.is_insurance
        FROM hospitalizations h
        JOIN beds b ON b.id = h.bed_id
        WHERE h.bed_id IS NOT NULL
    """)).fetchall()

    if rows:
        conn.execute(
            sa.text("""
                INSERT INTO hospitalization_bed_stays
                    (hospitalization_id, room_id, bed_id, price, is_insurance,
                     started_at, ended_at, assigned_by_id, created_at)
                VALUES
                    (:hid, :room_id, :bed_id, :price, :is_insurance,
                     :started_at, :ended_at, :assigned_by_id, :created_at)
            """),
            [{
                'hid': row[0],
                'room_id': row[1],
                'bed_id': row[2],
                'price': row[8],
                'is_insurance': row[9],
                'started_at': row[3] or row[4],
                'ended_at': row[5],
                'assigned_by_id': row[6] or row[7],
                'created_at': row[3] or row[4],
            } for row in rows],
        )


def downgrade():
    op.drop_table('hospitalization_bed_stays')

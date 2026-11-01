"""races: web discovery fields (date_estimated, poster, gpx)

Revision ID: s1a2b3c4d5f8
Revises: r1a2b3c4d5f7
Create Date: 2026-10-24 18:00:00.000000

Races found online (source='web', services/race_discovery_service.py) carry
the poster and the GPX in the row, and flag a next-edition date inferred from
past editions. Existing rows: date_estimated = false, the rest NULL.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 's1a2b3c4d5f8'
down_revision = 'r1a2b3c4d5f7'
branch_labels = None
depends_on = None


def _new_columns():
    return (
        sa.Column('date_estimated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('poster_data', sa.LargeBinary(), nullable=True),
        sa.Column('poster_mime', sa.String(length=32), nullable=True),
        sa.Column('gpx_data', sa.Text(), nullable=True),
    )


def _columns(conn, table):
    return {c['name'] for c in inspect(conn).get_columns(table)}


def upgrade():
    conn = op.get_bind()
    if 'races' not in inspect(conn).get_table_names():
        return
    existing = _columns(conn, 'races')
    for col in _new_columns():
        if col.name not in existing:
            op.add_column('races', col)


def downgrade():
    conn = op.get_bind()
    if 'races' not in inspect(conn).get_table_names():
        return
    existing = _columns(conn, 'races')
    with op.batch_alter_table('races') as batch_op:
        for col in _new_columns():
            if col.name in existing:
                batch_op.drop_column(col.name)

"""activities: race flag (is_race, race_source) + start coordinates

Revision ID: r1a2b3c4d5f7
Revises: q1a2b3c4d5f6
Create Date: 2026-09-25 18:00:00.000000

pred-review #96. `is_race` marks races so the prediction can weight them and
learn a personal race/training speed ratio. `race_source` says who decided:
'strava_flag' (Strava workout_type == 1) or 'user' (confirmed or rejected in
the "Your races" card); NULL = nobody decided yet, so the detector may still
propose it. start_lat/start_lng let the detector match the race calendar by
place, not only by date and distance.

Existing rows: is_race = false, the rest NULL. The Strava flag and the start
coordinates are backfilled from the list API on the next full resync
("reload activities"); no data backfill here.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'r1a2b3c4d5f7'
down_revision = 'q1a2b3c4d5f6'
branch_labels = None
depends_on = None


def _new_columns():
    return (
        sa.Column('is_race', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('race_source', sa.String(length=16), nullable=True),
        sa.Column('start_lat', sa.Float(), nullable=True),
        sa.Column('start_lng', sa.Float(), nullable=True),
    )


def _columns(conn, table):
    return {c['name'] for c in inspect(conn).get_columns(table)}


def upgrade():
    conn = op.get_bind()
    if 'activities' not in inspect(conn).get_table_names():
        return
    existing = _columns(conn, 'activities')
    for col in _new_columns():
        if col.name not in existing:
            op.add_column('activities', col)


def downgrade():
    conn = op.get_bind()
    if 'activities' not in inspect(conn).get_table_names():
        return
    existing = _columns(conn, 'activities')
    with op.batch_alter_table('activities') as batch_op:
        for col in _new_columns():
            if col.name in existing:
                batch_op.drop_column(col.name)

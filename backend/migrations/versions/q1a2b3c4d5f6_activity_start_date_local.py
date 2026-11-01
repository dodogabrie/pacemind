"""activities: add start_date_local (local calendar day for an activity)

Revision ID: q1a2b3c4d5f6
Revises: p1a2b3c4d5f5
Create Date: 2026-08-21 15:00:00.000000

Phase 2 of the multi-source epic. `start_date` is a UTC instant; the calendar
*day* an activity belongs to is a local reading of it, and training load and
plan compliance bucket by day. A 22:00 local run stored as 20:00Z is the same
day either way, but a 22:00 run in UTC+3 is not — it lands on tomorrow, and at
a week boundary it moves a whole week of ATL/CTL.

Nullable and left NULL for existing rows: `Activity.local_date` falls back to
the UTC date, which is exactly today's behaviour, so no backfill is needed and
nothing changes for a row until it is re-ingested.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'q1a2b3c4d5f6'
down_revision = 'p1a2b3c4d5f5'
branch_labels = None
depends_on = None


def _columns(conn, table):
    return {c['name'] for c in inspect(conn).get_columns(table)}


def upgrade():
    conn = op.get_bind()
    if 'activities' not in inspect(conn).get_table_names():
        return
    if 'start_date_local' not in _columns(conn, 'activities'):
        op.add_column('activities',
                      sa.Column('start_date_local', sa.DateTime(), nullable=True))


def downgrade():
    conn = op.get_bind()
    if 'activities' not in inspect(conn).get_table_names():
        return
    if 'start_date_local' in _columns(conn, 'activities'):
        with op.batch_alter_table('activities') as batch_op:
            batch_op.drop_column('start_date_local')

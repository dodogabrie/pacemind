"""sync_status: resync_pending

Revision ID: t1a2b3c4d5f9
Revises: s1a2b3c4d5f8
Create Date: 2026-10-25 08:00:00.000000

A Strava push event that lands while a sync is running sets this flag; the
running sync re-runs once (incremental) when it finishes, so the new activity
is not lost until the next 6 h stale check.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 't1a2b3c4d5f9'
down_revision = 's1a2b3c4d5f8'
branch_labels = None
depends_on = None


def _columns(conn):
    return {c['name'] for c in inspect(conn).get_columns('sync_status')}


def upgrade():
    conn = op.get_bind()
    if 'sync_status' not in inspect(conn).get_table_names():
        return
    if 'resync_pending' not in _columns(conn):
        op.add_column('sync_status', sa.Column('resync_pending', sa.Boolean(),
                                               nullable=False, server_default=sa.false()))


def downgrade():
    conn = op.get_bind()
    if 'sync_status' not in inspect(conn).get_table_names():
        return
    if 'resync_pending' in _columns(conn):
        with op.batch_alter_table('sync_status') as batch_op:
            batch_op.drop_column('resync_pending')

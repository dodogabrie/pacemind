"""strava_activities -> activities: multi-source activity storage

Revision ID: p1a2b3c4d5f5
Revises: o1a2b3c4d5f4
Create Date: 2026-08-21 12:30:00.000000

Phase 1 of the multi-source epic. The table is *evolved*, not replaced — a
parallel `activities` table would mean a dual-write period and a long tail of
"which table is authoritative" bugs. See
docs/plans/multi-source-activities/02-activity-abstraction.md.

Six guarded steps, each independently re-runnable:

1. rename `strava_activities` -> `activities`
2. add source/external_id/dedup_key/sport_type/moving_time_s/elapsed_time_s/
   elevation_gain_m, then backfill source='strava' + external_id=strava_id
3. backfill `dedup_key` (sha256 in Python — the formula is not portable SQL and
   is inlined here on purpose so a later change to models/activity.py cannot
   retroactively invalidate what this migration wrote)
4. `strava_id` -> nullable, then the UNIQUE + the two indices
5. `sync_status`: add `provider`, relax UNIQUE(user_id) to UNIQUE(user_id, provider)
6. `user_activity_residuals`: add `source`

Index/FK carry-through across the rename differs between SQLite (dev) and
Postgres (prod), and a SQLite batch rebuild drops indices it cannot reflect.
Step 4 therefore re-asserts every index by name *after* all rebuilds rather
than trusting either engine to carry them.

Downgrade renames the table back and drops the indices this added. The new
columns are data-bearing (a non-Strava row's whole identity lives in
source/external_id) and are deliberately kept — an old codebase ignores them.
"""
import hashlib
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'p1a2b3c4d5f5'
down_revision = 'o1a2b3c4d5f4'
branch_labels = None
depends_on = None


NEW_ACTIVITY_COLUMNS = (
    ('source', sa.String(length=32), 'strava'),
    ('external_id', sa.String(length=128), None),
    ('dedup_key', sa.String(length=64), None),
    ('sport_type', sa.String(length=32), None),
    ('moving_time_s', sa.Integer(), None),
    ('elapsed_time_s', sa.Integer(), None),
    ('elevation_gain_m', sa.Float(), None),
)


def _table_exists(conn, table: str) -> bool:
    return table in inspect(conn).get_table_names()


def _columns(conn, table: str) -> dict:
    return {c['name']: c for c in inspect(conn).get_columns(table)}


def _index_names(conn, table: str) -> set:
    return {i['name'] for i in inspect(conn).get_indexes(table)}


def _unique_names(conn, table: str) -> set:
    return {u['name'] for u in inspect(conn).get_unique_constraints(table)}


def _as_utc(value):
    """SQLite hands back a string here, Postgres a datetime. Normalise to UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    # The app has always written UTC into this column.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _dedup_key(user_id, start_ts: float, distance_m) -> str:
    """Content key for a session. Must match models.activity.make_dedup_key."""
    raw = f"{user_id}|{round(start_ts / 60)}|{round((distance_m or 0) / 50)}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def upgrade():
    conn = op.get_bind()

    # ── 1. rename ────────────────────────────────────────────────────────────
    if not _table_exists(conn, 'activities'):
        if not _table_exists(conn, 'strava_activities'):
            # Bare DB — init_db()/create_all() materialises everything from the
            # models, which already carry the final shape.
            _upgrade_sync_status(conn)
            _upgrade_residuals(conn)
            return
        op.rename_table('strava_activities', 'activities')

    # ── 2. new columns + source/external_id backfill ─────────────────────────
    existing = _columns(conn, 'activities')
    missing = [c for c in NEW_ACTIVITY_COLUMNS if c[0] not in existing]
    for name, col_type, default in missing:
        op.add_column('activities',
                      sa.Column(name, col_type, nullable=True,
                                server_default=default))

    # Idempotent: only touches rows the backfill has not reached.
    conn.execute(sa.text(
        "UPDATE activities SET source = 'strava' WHERE source IS NULL"
    ))
    conn.execute(sa.text(
        "UPDATE activities SET external_id = CAST(strava_id AS VARCHAR) "
        "WHERE external_id IS NULL AND strava_id IS NOT NULL"
    ))

    # ── 3. dedup_key backfill ────────────────────────────────────────────────
    rows = conn.execute(sa.text(
        "SELECT id, user_id, start_date, distance FROM activities "
        "WHERE dedup_key IS NULL"
    )).fetchall()
    for row in rows:
        start = _as_utc(row.start_date)
        if start is None:
            continue  # start_date is NOT NULL; belt-and-braces for odd drivers
        conn.execute(
            sa.text("UPDATE activities SET dedup_key = :k WHERE id = :i"),
            {'k': _dedup_key(row.user_id, start.timestamp(), row.distance),
             'i': row.id},
        )

    # ── 4. strava_id nullable + constraints ──────────────────────────────────
    if not _columns(conn, 'activities')['strava_id']['nullable']:
        with op.batch_alter_table('activities') as batch_op:
            batch_op.alter_column('strava_id', existing_type=sa.BigInteger(),
                                  nullable=True)

    # Re-assert indices by name AFTER the rename and any batch rebuild —
    # neither engine is trusted to have carried them through.
    indices = _index_names(conn, 'activities')
    if 'ix_strava_activity_user_date' not in indices:
        op.create_index('ix_strava_activity_user_date', 'activities',
                        ['user_id', 'start_date'])
    if 'ix_activity_user_dedup' not in indices:
        op.create_index('ix_activity_user_dedup', 'activities',
                        ['user_id', 'dedup_key'])
    if 'uq_activity_user_source_external' not in _unique_names(conn, 'activities'):
        # A UNIQUE over nullable columns permits many NULL external_ids on both
        # engines, which is what pre-backfill rows and upload rows need.
        with op.batch_alter_table('activities') as batch_op:
            batch_op.create_unique_constraint(
                'uq_activity_user_source_external',
                ['user_id', 'source', 'external_id'])

    _upgrade_sync_status(conn)
    _upgrade_residuals(conn)


def _upgrade_sync_status(conn):
    """provider column + UNIQUE(user_id) -> UNIQUE(user_id, provider)."""
    if not _table_exists(conn, 'sync_status'):
        return
    if 'provider' not in _columns(conn, 'sync_status'):
        op.add_column('sync_status',
                      sa.Column('provider', sa.String(length=32), nullable=True,
                                server_default='strava'))
    conn.execute(sa.text(
        "UPDATE sync_status SET provider = 'strava' WHERE provider IS NULL"))

    if 'uq_sync_status_user_provider' in _unique_names(conn, 'sync_status'):
        return

    # The old constraint is unnamed (declared inline as `user_id UNIQUE`), so
    # it cannot be dropped by name on either engine. Rebuild the table from an
    # explicit definition: reflection alone would faithfully re-create the very
    # constraint we are trying to remove.
    sync_status = sa.Table(
        'sync_status', sa.MetaData(),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=True,
                  server_default='strava'),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('current_step', sa.String(length=100), nullable=True),
        sa.Column('total_activities', sa.Integer(), nullable=True),
        sa.Column('downloaded_activities', sa.Integer(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    if conn.dialect.name == 'sqlite':
        with op.batch_alter_table('sync_status', copy_from=sync_status) as batch_op:
            batch_op.create_unique_constraint(
                'uq_sync_status_user_provider', ['user_id', 'provider'])
    else:
        # Postgres: drop the auto-named unique index behind the old constraint.
        for name in _unique_names(conn, 'sync_status'):
            op.drop_constraint(name, 'sync_status', type_='unique')
        op.create_unique_constraint('uq_sync_status_user_provider',
                                    'sync_status', ['user_id', 'provider'])


def _upgrade_residuals(conn):
    """Record which ingest source produced the streams behind each residual."""
    if not _table_exists(conn, 'user_activity_residuals'):
        return
    if 'source' not in _columns(conn, 'user_activity_residuals'):
        op.add_column('user_activity_residuals',
                      sa.Column('source', sa.String(length=32), nullable=True))
    conn.execute(sa.text(
        "UPDATE user_activity_residuals SET source = 'strava' "
        "WHERE source IS NULL"))


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'activities'):
        return
    indices = _index_names(conn, 'activities')
    if 'ix_activity_user_dedup' in indices:
        op.drop_index('ix_activity_user_dedup', table_name='activities')
    if 'uq_activity_user_source_external' in _unique_names(conn, 'activities'):
        with op.batch_alter_table('activities') as batch_op:
            batch_op.drop_constraint('uq_activity_user_source_external',
                                     type_='unique')
    if not _table_exists(conn, 'strava_activities'):
        op.rename_table('activities', 'strava_activities')
        if 'ix_strava_activity_user_date' not in _index_names(conn, 'strava_activities'):
            op.create_index('ix_strava_activity_user_date', 'strava_activities',
                            ['user_id', 'start_date'])
    # strava_id stays nullable and the new columns stay: non-Strava rows have
    # no strava_id to put back, so restoring NOT NULL would fail on exactly the
    # rows this migration enabled.

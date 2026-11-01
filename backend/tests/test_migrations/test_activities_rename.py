"""End-to-end check of the strava_activities -> activities migration.

Runs the real Alembic chain against a temporary SQLite file, seeds rows at the
previous revision, upgrades, and asserts the things that would silently lose or
corrupt user data:

  - every pre-existing row survives with source='strava'
  - external_id / dedup_key are backfilled
  - the FK from workout_completions still points at the renamed table
  - ix_strava_activity_user_date survived the rename (SQLite carries indices
    through ALTER TABLE RENAME, but a batch rebuild can drop them — the
    migration re-asserts by name, this proves it)
  - sync_status accepts two providers per user
  - re-running is a no-op
"""

import pytest
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import inspect, text

from app import create_app
from database import db

PREVIOUS_REVISION = 'o1a2b3c4d5f4'


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{tmp_path / 'fixture.db'}"
    app.config['TESTING'] = True
    with app.app_context():
        yield app
        db.session.remove()


def _seed(n=3):
    db.session.execute(text(
        "INSERT INTO users (strava_user_id, strava_username) VALUES (7, 'runner')"))
    for i in range(n):
        db.session.execute(
            text("INSERT INTO strava_activities "
                 "  (user_id, strava_id, name, distance, start_date) "
                 "VALUES (1, :sid, :name, :dist, :start)"),
            {'sid': 900 + i, 'name': f'Run {i}', 'dist': 10000 + 137 * i,
             'start': f'2026-0{i + 1}-01 08:00:00'},
        )
    db.session.execute(text(
        "INSERT INTO sync_status (user_id, status) VALUES (1, 'idle')"))
    db.session.commit()


def test_rename_preserves_rows_indices_and_fks(app):
    alembic_upgrade(revision=PREVIOUS_REVISION)
    _seed()

    alembic_upgrade()  # head

    rows = db.session.execute(text(
        "SELECT strava_id, source, external_id, dedup_key FROM activities "
        "ORDER BY strava_id")).fetchall()
    assert len(rows) == 3
    assert all(r.source == 'strava' for r in rows)
    assert [r.external_id for r in rows] == ['900', '901', '902']
    # Distinct sessions must not collapse onto one key.
    assert len({r.dedup_key for r in rows}) == 3
    assert all(len(r.dedup_key) == 32 for r in rows)

    insp = inspect(db.engine)
    assert 'strava_activities' not in insp.get_table_names()
    index_names = {i['name'] for i in insp.get_indexes('activities')}
    assert 'ix_strava_activity_user_date' in index_names
    assert 'ix_activity_user_dedup' in index_names
    assert 'uq_activity_user_source_external' in {
        u['name'] for u in insp.get_unique_constraints('activities')}
    # strava_id relaxed to nullable for non-Strava sources.
    assert {c['name']: c['nullable'] for c in insp.get_columns('activities')}['strava_id']

    # The FK on workout_completions must follow the rename, not dangle.
    fk_targets = {fk['referred_table']
                  for fk in insp.get_foreign_keys('workout_completions')}
    assert 'activities' in fk_targets
    assert 'strava_activities' not in fk_targets


def test_dedup_key_backfill_matches_the_model(app):
    alembic_upgrade(revision=PREVIOUS_REVISION)
    _seed(n=1)
    alembic_upgrade()

    from datetime import datetime, timezone
    from models.activity import make_dedup_key

    row = db.session.execute(text(
        "SELECT user_id, start_date, distance, dedup_key FROM activities")).fetchone()
    expected = make_dedup_key(
        row.user_id, datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc), row.distance)
    assert row.dedup_key == expected


def test_sync_status_allows_one_row_per_provider(app):
    alembic_upgrade(revision=PREVIOUS_REVISION)
    _seed(n=0)
    alembic_upgrade()

    assert db.session.execute(text(
        "SELECT provider FROM sync_status")).scalar() == 'strava'
    db.session.execute(text(
        "INSERT INTO sync_status (user_id, provider, status) "
        "VALUES (1, 'upload', 'idle')"))
    db.session.commit()
    assert db.session.execute(text("SELECT COUNT(*) FROM sync_status")).scalar() == 2


def test_upgrade_is_rerunnable(app):
    alembic_upgrade(revision=PREVIOUS_REVISION)
    _seed()
    alembic_upgrade()
    before = db.session.execute(text(
        "SELECT id, dedup_key FROM activities ORDER BY id")).fetchall()

    alembic_upgrade()  # already at head — must be a no-op, not a re-backfill

    assert db.session.execute(text(
        "SELECT id, dedup_key FROM activities ORDER BY id")).fetchall() == before

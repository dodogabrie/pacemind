"""Shared test setup: every test runs against an isolated in-memory SQLite."""

import sys
import os

# ---------------------------------------------------------------------------
# DB safety guard — MUST run before any `from app import ...` or `from database
# import db` elsewhere. Forces every test to hit an isolated in-memory SQLite,
# no matter what DATABASE_URL is set to in the environment. Prevents the
# `db.drop_all()` teardown in test fixtures from wiping the dev Postgres.
# ---------------------------------------------------------------------------
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ.setdefault('FLASK_ENV', 'testing')

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest


@pytest.fixture(autouse=True)
def _assert_test_db_is_sqlite():
    """Fail loudly if anything tries to run tests against a real Postgres.

    Runs before every test. If a test somehow rebinds SQLAlchemy to Postgres
    (e.g. forgetting the `SQLALCHEMY_DATABASE_URI` override), this fixture
    stops the suite before `db.drop_all()` can hurt the dev database.
    """
    try:
        from flask import has_app_context
        from database import db
    except Exception:
        return  # database module not importable — not a DB-using test
    if not has_app_context():
        return
    try:
        driver = db.engine.url.drivername
    except Exception:
        return
    if 'sqlite' not in driver.lower():
        raise RuntimeError(
            f"Refusing to run tests against non-SQLite DB (driver={driver!r}). "
            f"Check your test fixture — SQLALCHEMY_DATABASE_URI must be set "
            f"BEFORE calling create_app() / db.init_app(), not after."
        )

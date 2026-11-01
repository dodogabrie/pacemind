"""End-to-end check of the user_connections migration on a fixture DB.

Runs the real Alembic chain against a temporary SQLite file, seeds a
Strava-shaped user at the previous revision, then upgrades and asserts the
copied token still decrypts — the one failure mode that would log every
existing user out of Strava.
"""

import pytest
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade
from sqlalchemy import inspect, text

from app import create_app
from database import db
from models._crypto import cipher

PREVIOUS_REVISION = 'n1a2b3c4d5f3'


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{tmp_path / 'fixture.db'}"
    app.config['TESTING'] = True
    with app.app_context():
        yield app
        db.session.remove()


def test_backfill_preserves_encrypted_tokens(app):
    alembic_upgrade(revision=PREVIOUS_REVISION)

    access = cipher.encrypt(b'strava-access-token')
    refresh = cipher.encrypt(b'strava-refresh-token')
    db.session.execute(
        text("INSERT INTO users (strava_user_id, strava_username, access_token, "
             "refresh_token, expires_at) "
             "VALUES (4242, 'runner', :a, :r, 1700000000)"),
        {'a': access, 'r': refresh},
    )
    db.session.commit()

    alembic_upgrade()  # head

    row = db.session.execute(
        text("SELECT user_id, provider, external_user_id, access_token, "
             "refresh_token, expires_at, status FROM user_connections")
    ).fetchall()
    assert len(row) == 1
    user_id, provider, external_id, at, rt, expires_at, status = row[0]
    assert (provider, external_id, expires_at, status) == ('strava', '4242', 1700000000, 'active')
    # Bytes copied verbatim → still decryptable with the same key.
    assert cipher.decrypt(at) == b'strava-access-token'
    assert cipher.decrypt(rt) == b'strava-refresh-token'

    # Re-running must not duplicate the connection.
    alembic_upgrade()
    assert db.session.execute(text("SELECT COUNT(*) FROM user_connections")).scalar() == 1

    # The seeded user survived the table rebuild intact.
    assert db.session.execute(
        text("SELECT strava_username FROM users WHERE id = :i"), {'i': user_id}
    ).scalar() == 'runner'

    # Downgrade drops only the new table; nothing data-bearing on users goes.
    alembic_downgrade(revision=PREVIOUS_REVISION)
    assert 'user_connections' not in inspect(db.engine).get_table_names()
    assert db.session.execute(
        text("SELECT strava_username FROM users WHERE id = :i"), {'i': user_id}
    ).scalar() == 'runner'


def test_users_accepts_email_only_account_after_upgrade(app):
    alembic_upgrade()

    columns = {c['name']: c for c in inspect(db.engine).get_columns('users')}
    assert columns['strava_user_id']['nullable'] is True
    assert {'password_hash', 'auth_provider', 'email_verified_at'} <= set(columns)

    db.session.execute(text(
        "INSERT INTO users (email, auth_provider) VALUES ('email@only.io', 'email')"))
    db.session.commit()
    assert db.session.execute(
        text("SELECT strava_user_id FROM users WHERE email = 'email@only.io'")
    ).scalar() is None

    # The unique index on strava_user_id survived the rebuild.
    uniques = {tuple(u['column_names']) for u in inspect(db.engine).get_unique_constraints('users')}
    assert ('strava_user_id',) in uniques
    assert ('email',) in uniques

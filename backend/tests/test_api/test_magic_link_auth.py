"""Magic-link login: happy path, single use, expiry, and Strava link collisions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from app import create_app
from database import db
from models import User, UserConnection
from services.connection_service import ConnectionConflictError, ConnectionService


@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sent_links():
    """Capture the links the mailer would send."""
    captured = []

    def _capture(to, subject, body):
        captured.append((to, body.split('token=')[1].split()[0] if 'token=' in body else None))
        return False

    with patch('api.auth.send_email', side_effect=_capture):
        yield captured


def _request_link(client, email):
    return client.post('/api/auth/magic-link', json={'email': email})


# ── request ────────────────────────────────────────────────────────────────

def test_magic_link_request_always_202(client, sent_links):
    assert _request_link(client, 'new@runner.io').status_code == 202
    assert len(sent_links) == 1
    assert sent_links[0][0] == 'new@runner.io'


def test_magic_link_request_rejects_bad_email(client, sent_links):
    resp = _request_link(client, 'not-an-email')
    assert resp.status_code == 400
    assert sent_links == []


def test_magic_link_no_enumeration_for_unverified_strava_account(app, client, sent_links):
    with app.app_context():
        db.session.add(User(strava_user_id=42, email='athlete@strava.io'))
        db.session.commit()

    # Same 202, but nothing is sent: that address was never verified by us.
    assert _request_link(client, 'athlete@strava.io').status_code == 202
    assert sent_links == []


# ── verify ─────────────────────────────────────────────────────────────────

def test_magic_link_happy_path_creates_account_and_logs_in(app, client, sent_links):
    _request_link(client, 'new@runner.io')
    token = sent_links[0][1]

    resp = client.get(f'/api/auth/magic-link/verify?token={token}')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/auth-success')
    assert 'jwt_token' in resp.headers.get('Set-Cookie', '')

    status = client.get('/api/auth/status')
    assert status.status_code == 200
    body = status.get_json()['user']
    assert body['email'] == 'new@runner.io'
    assert body['auth_provider'] == 'email'
    assert body['strava_user_id'] is None

    with app.app_context():
        user = User.query.filter_by(email='new@runner.io').one()
        assert user.email_verified_at is not None


def test_magic_link_is_single_use(app, client, sent_links):
    _request_link(client, 'new@runner.io')
    token = sent_links[0][1]

    assert client.get(f'/api/auth/magic-link/verify?token={token}').headers['Location'].endswith('/auth-success')

    replay = client.get(f'/api/auth/magic-link/verify?token={token}')
    assert 'error=invalid_link' in replay.headers['Location']

    with app.app_context():
        assert User.query.filter_by(email='new@runner.io').count() == 1


def test_magic_link_expires(app, client):
    with app.app_context():
        payload = {
            'email': 'new@runner.io',
            'purpose': 'magic_link',
            'exp': datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        key = f"{app.config['JWT_SECRET_KEY']}|magic_link|signup"
        token = jwt.encode(payload, key, algorithm='HS256')

    resp = client.get(f'/api/auth/magic-link/verify?token={token}')
    assert 'error=link_expired' in resp.headers['Location']
    with app.app_context():
        assert User.query.count() == 0


def test_magic_link_rejects_foreign_purpose_token(app, client):
    """A session JWT must not double as a magic link."""
    with app.app_context():
        token = jwt.encode({'user_id': 1,
                            'email': 'new@runner.io',
                            'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
                           f"{app.config['JWT_SECRET_KEY']}|magic_link|signup",
                           algorithm='HS256')

    resp = client.get(f'/api/auth/magic-link/verify?token={token}')
    assert 'error=invalid_link' in resp.headers['Location']


def test_magic_link_rejects_tampered_token(client, sent_links):
    _request_link(client, 'new@runner.io')
    token = sent_links[0][1]
    resp = client.get(f'/api/auth/magic-link/verify?token={token[:-2]}xy')
    assert 'error=invalid_link' in resp.headers['Location']


def test_magic_link_rate_limited(client, sent_links):
    codes = [_request_link(client, f'runner{i}@x.io').status_code for i in range(12)]
    assert 429 in codes, "magic-link requests should be rate limited per IP"


# ── Strava linking ─────────────────────────────────────────────────────────

def test_strava_link_collision(app):
    """An athlete already linked elsewhere cannot be attached to a second account."""
    with app.app_context():
        owner = User(strava_user_id=99, strava_username='owner')
        other = User(email='other@runner.io', auth_provider='email')
        db.session.add_all([owner, other])
        db.session.commit()

        service = ConnectionService()
        service.link_strava(owner, {'id': 99, 'username': 'owner'},
                            {'access_token': 'a', 'refresh_token': 'r', 'expires_at': 1})
        db.session.commit()

        with pytest.raises(ConnectionConflictError):
            service.link_strava(other, {'id': 99, 'username': 'owner'})


def test_strava_link_attaches_to_logged_in_user(app):
    with app.app_context():
        user = User(email='other@runner.io', auth_provider='email')
        db.session.add(user)
        db.session.commit()

        ConnectionService().link_strava(
            user, {'id': 1234, 'username': 'runner'},
            {'access_token': 'a', 'refresh_token': 'r', 'expires_at': 99}, 'read,activity:read')
        db.session.commit()

        connection = UserConnection.query.filter_by(user_id=user.id, provider='strava').one()
        assert connection.external_user_id == '1234'
        assert connection.access_token == 'a'
        assert connection.scopes == 'read,activity:read'
        # Legacy columns stay in sync for the ~9 readers that still use them.
        assert user.strava_user_id == 1234
        assert user.access_token == 'a'


def test_strava_callback_creates_user_and_connection(app, client):
    token_data = {
        'access_token': 'at', 'refresh_token': 'rt', 'expires_at': 123,
        'athlete': {'id': 555, 'username': 'newbie'},
    }
    with patch('api.auth.get_strava_service') as get_service, \
         patch('api.auth.StravaSyncService'):
        get_service.return_value.exchange_code.return_value = token_data
        resp = client.get('/api/auth/callback?code=abc')

    assert resp.headers['Location'].endswith('/auth-success')
    with app.app_context():
        user = User.query.filter_by(strava_user_id=555).one()
        connection = UserConnection.query.filter_by(user_id=user.id).one()
        assert connection.provider == 'strava'
        assert connection.refresh_token == 'rt'


def test_strava_callback_conflict_redirects_with_error(app, client):
    with app.app_context():
        owner = User(strava_user_id=555)
        logged_in = User(email='other@runner.io', auth_provider='email')
        db.session.add_all([owner, logged_in])
        db.session.commit()
        ConnectionService().link_strava(owner, {'id': 555})
        db.session.commit()
        logged_in_id = logged_in.id

    from api.auth import generate_jwt
    with app.app_context():
        client.set_cookie('jwt_token', generate_jwt(logged_in_id), domain='localhost')

    token_data = {'access_token': 'at', 'refresh_token': 'rt', 'expires_at': 1,
                  'athlete': {'id': 555, 'username': 'owner'}}
    with patch('api.auth.get_strava_service') as get_service, \
         patch('api.auth.StravaSyncService'):
        get_service.return_value.exchange_code.return_value = token_data
        resp = client.get('/api/auth/callback?code=abc')

    assert 'error=strava_already_linked' in resp.headers['Location']
    with app.app_context():
        assert UserConnection.query.filter_by(user_id=logged_in_id).count() == 0


def test_disconnect_keeps_account(app, client):
    with app.app_context():
        user = User(strava_user_id=777, email='keep@runner.io', auth_provider='email',
                    email_verified_at=datetime.now(timezone.utc))
        db.session.add(user)
        db.session.commit()
        ConnectionService().link_strava(user, {'id': 777},
                                        {'access_token': 'a', 'refresh_token': 'r',
                                         'expires_at': 1})
        db.session.commit()
        user_id = user.id
        from api.auth import generate_jwt
        client.set_cookie('jwt_token', generate_jwt(user_id), domain='localhost')

    assert client.delete('/api/auth/connections/strava').status_code == 200
    assert client.get('/api/auth/status').status_code == 200
    with app.app_context():
        assert UserConnection.query.filter_by(user_id=user_id).one().status == 'revoked'
        assert db.session.get(User, user_id) is not None


def test_status_for_anonymous_visitor_is_200_not_authenticated(client):
    resp = client.get('/api/auth/status')
    assert resp.status_code == 200
    assert resp.get_json() == {'authenticated': False}

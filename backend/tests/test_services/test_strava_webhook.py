from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models.user import User


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


def test_webhook(app):
    client = app.test_client()
    app.config['STRAVA_WEBHOOK_VERIFY_TOKEN'] = 'tok'
    assert client.get('/api/strava/webhook/tok?hub.verify_token=bad&hub.challenge=x').status_code == 404
    assert client.post('/api/strava/webhook/bad', json={}).status_code == 404
    r = client.get('/api/strava/webhook/tok?hub.verify_token=tok&hub.challenge=x')
    assert r.get_json() == {'hub.challenge': 'x'}

    u = User(strava_user_id=42)
    u.access_token, u.refresh_token = 'a', 'r'
    db.session.add(u)
    db.session.commit()
    uid = u.id

    with patch('api.strava.StravaSyncService.sync_if_stale') as s:
        client.post('/api/strava/webhook/tok', json={'object_type': 'activity', 'aspect_type': 'create', 'owner_id': 42})
        s.assert_called_once_with(uid, max_age_hours=0)
        client.post('/api/strava/webhook/tok', json={'object_type': 'activity', 'aspect_type': 'create', 'owner_id': 999})
        assert s.call_count == 1

    client.post('/api/strava/webhook/tok', json={'object_type': 'athlete', 'owner_id': 42, 'updates': {'authorized': 'false'}})
    db.session.expire_all()
    assert db.session.get(User, uid).refresh_token is None

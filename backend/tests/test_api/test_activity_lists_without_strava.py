"""Email / file-import users have no Strava tokens: activity lists must be empty, not 500."""

import pytest

from api.auth import generate_jwt
from app import create_app
from database import db
from models import User


@pytest.fixture
def client():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        user = User(email='file@runner.io', auth_provider='email')
        db.session.add(user)
        db.session.commit()
        client = app.test_client()
        client.set_cookie(key='jwt_token', value=generate_jwt(user.id), domain='localhost')
        yield client
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize('path', ['/api/strava/activities', '/api/prediction/calibration-activities'])
def test_list_is_empty_without_strava(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.get_json() == {'activities': [], 'total': 0, 'strava_connected': False}

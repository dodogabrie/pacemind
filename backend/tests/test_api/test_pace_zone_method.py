"""Tests for the pace-zone-method endpoint on /api/training-plan."""

from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from database import db
from models import User, UserTrainingPreferences


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
def user(app):
    with app.app_context():
        u = User(strava_user_id=8888, strava_username='pz-method-user')
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def auth_user(app, user):
    mock = MagicMock()
    mock.id = user
    with patch('api.training_plan.get_current_user', return_value=mock):
        yield mock


def test_set_vdot_persists_method_and_race(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.put('/api/training-plan/pace-zone-method', json={
            'method': 'vdot',
            'race_distance_m': 5000,
            'race_time_s': 1200,
        })
        assert resp.status_code == 200
        assert resp.get_json()['pace_zone_method'] == 'vdot'

        prefs = UserTrainingPreferences.query.filter_by(user_id=user).one()
        assert prefs.pace_zone_method == 'vdot'
        assert prefs.pace_zone_race_distance_m == 5000
        assert prefs.pace_zone_race_time_s == 1200


def test_vdot_requires_race(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.put('/api/training-plan/pace-zone-method', json={'method': 'vdot'})
        assert resp.status_code == 400


def test_invalid_method_rejected(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.put('/api/training-plan/pace-zone-method', json={'method': 'bogus'})
        assert resp.status_code == 400


def test_physics_clears_stale_race(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        client.put('/api/training-plan/pace-zone-method', json={
            'method': 'riegel', 'race_distance_m': 10000, 'race_time_s': 2400,
        })
        resp = client.put('/api/training-plan/pace-zone-method', json={'method': 'physics'})
        assert resp.status_code == 200

        prefs = UserTrainingPreferences.query.filter_by(user_id=user).one()
        assert prefs.pace_zone_method == 'physics'
        assert prefs.pace_zone_race_distance_m is None
        assert prefs.pace_zone_race_time_s is None


def test_get_pace_zones_preview_with_query(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.get(
            '/api/training-plan/pace-zones',
            query_string={'method': 'vdot', 'race_distance_m': 5000, 'race_time_s': 1200},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['method'] == 'vdot'
        assert body['requested_method'] == 'vdot'
        assert 'vdot' in body['method_meta']

"""Tests for the HR-anchor endpoints on /api/training-plan (#59)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from database import db
from models import User, Activity


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
        u = User(strava_user_id=9191, strava_username='hr-user')
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def auth_user(app, user):
    mock = MagicMock()
    mock.id = user
    with patch('api.training_plan.get_current_user', return_value=mock):
        yield mock


def _client(app):
    return app.test_client()


class TestUpdateHrAnchors:
    def test_persists_and_returns_zones(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr',
                                    json={'hr_max': 190, 'hr_rest': 50})
            assert resp.status_code == 200
            body = resp.get_json()
            assert body['hr_max'] == 190
            assert body['hr_rest'] == 50
            assert body['hr_basis'] == 'karvonen'
            assert 'easy' in body['hr_zones']

    def test_lthr_only(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr',
                                    json={'lthr': 168})
            assert resp.status_code == 200
            assert resp.get_json()['hr_basis'] == 'lthr'

    def test_rejects_out_of_range(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr',
                                    json={'hr_max': 999})
            assert resp.status_code == 400

    def test_rejects_rest_above_max(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr',
                                    json={'hr_max': 180, 'hr_rest': 185})
            assert resp.status_code == 400

    def test_rejects_lthr_above_max(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr',
                                    json={'hr_max': 180, 'lthr': 190})
            assert resp.status_code == 400

    def test_consistency_check_uses_stored_value(self, app, user, auth_user):
        """hr_max stored in a prior request still constrains a later hr_rest."""
        with app.app_context():
            client = _client(app)
            client.put('/api/training-plan/pace-zones/hr', json={'hr_max': 180})
            resp = client.put('/api/training-plan/pace-zones/hr', json={'hr_rest': 185})
            assert resp.status_code == 400

    def test_empty_payload_rejected(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).put('/api/training-plan/pace-zones/hr', json={})
            assert resp.status_code == 400

    def test_clear_with_null(self, app, user, auth_user):
        with app.app_context():
            client = _client(app)
            client.put('/api/training-plan/pace-zones/hr', json={'hr_max': 190})
            resp = client.put('/api/training-plan/pace-zones/hr', json={'hr_max': None})
            assert resp.status_code == 200
            assert resp.get_json()['hr_max'] is None
            assert resp.get_json()['hr_basis'] is None


class TestGetPaceZonesIncludesHr:
    def test_hr_zones_present_after_set(self, app, user, auth_user):
        with app.app_context():
            client = _client(app)
            client.put('/api/training-plan/pace-zones/hr', json={'hr_max': 190, 'hr_rest': 50})
            resp = client.get('/api/training-plan/pace-zones')
            assert resp.status_code == 200
            body = resp.get_json()
            assert body['hr_basis'] == 'karvonen'
            assert body['hr_zones']['easy']['min_bpm'] > 0

    def test_hr_zones_null_when_unset(self, app, user, auth_user):
        with app.app_context():
            resp = _client(app).get('/api/training-plan/pace-zones')
            assert resp.status_code == 200
            assert resp.get_json()['hr_zones'] is None


class TestAutodetectHrMax:
    def _add_activity(self, user_id, hr_samples, days_ago=10):
        act = Activity(
            user_id=user_id,
            strava_id=1000 + days_ago,
            name='run',
            distance=10000.0,
            start_date=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        act.streams = {'heartrate': hr_samples}
        db.session.add(act)
        db.session.commit()

    def test_estimate_from_streams(self, app, user, auth_user):
        with app.app_context():
            self._add_activity(user, [120, 150, 178])
            resp = _client(app).post('/api/training-plan/pace-zones/hr/autodetect')
            assert resp.status_code == 200
            body = resp.get_json()
            assert body['hr_max_estimate'] == 182  # 178 * 1.02
            assert body['activities_scanned'] == 1

    def test_no_hr_data(self, app, user, auth_user):
        with app.app_context():
            self._add_activity(user, [])
            resp = _client(app).post('/api/training-plan/pace-zones/hr/autodetect')
            assert resp.status_code == 200
            assert resp.get_json()['hr_max_estimate'] is None

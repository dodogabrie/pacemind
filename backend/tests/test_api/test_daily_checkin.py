"""Tests for the daily check-in endpoints on /api/training-plan."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from database import db
from models import DailyCheckin, TrainingPlan, User


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
        u = User(strava_user_id=7777, strava_username='checkin-api-user')
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def auth_user(app, user):
    mock = MagicMock()
    mock.id = user
    mock.saved_flat_pace = None
    with patch('api.training_plan.get_current_user', return_value=mock):
        yield mock


@pytest.fixture
def plan(app, user):
    with app.app_context():
        today = datetime.now(timezone.utc).date()
        monday = today - timedelta(days=today.weekday())
        p = TrainingPlan(
            user_id=user,
            plan_name='Race Plan',
            status='active',
            created_at=datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc),
            weeks=[{
                'week_number': 1,
                'start_date': monday.isoformat(),
                'days': [
                    {'day': 'Monday', 'workout_type': 'easy'},
                    {'day': 'Tuesday', 'workout_type': 'easy'},
                    {'day': 'Wednesday', 'workout_type': 'easy'},
                    {'day': 'Thursday', 'workout_type': 'easy'},
                    {'day': 'Friday', 'workout_type': 'easy'},
                    {'day': 'Saturday', 'workout_type': 'easy'},
                    {'day': 'Sunday', 'workout_type': 'long_run'},
                ],
            }],
        )
        db.session.add(p)
        db.session.commit()
        return p.id


def test_post_checkin_persists_row(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        resp = client.post(
            f'/api/training-plan/{plan}/checkin',
            json={'feeling': 'good', 'rpe_yesterday': 5, 'sleep_h': 7.5, 'soreness': 2},
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['checkin']['feeling'] == 'good'
        assert body['checkin']['rpe_yesterday'] == 5
        # Good day, easy plan → no adjustments.
        assert body['adjustments']['adjusted'] == []

        # Row exists.
        row = DailyCheckin.query.filter_by(user_id=user).first()
        assert row is not None
        assert row.feeling == 'good'


def test_post_checkin_upserts_on_same_day(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        client.post(
            f'/api/training-plan/{plan}/checkin', json={'feeling': 'good', 'sleep_h': 8.0}
        )
        resp = client.post(
            f'/api/training-plan/{plan}/checkin',
            json={'feeling': 'tired', 'sleep_h': 6.0, 'rpe_yesterday': 7},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['checkin']['feeling'] == 'tired'
        assert body['checkin']['rpe_yesterday'] == 7
        assert body['checkin']['sleep_h'] == 6.0

        rows = DailyCheckin.query.filter_by(user_id=user).all()
        assert len(rows) == 1  # one row, mutated


def test_post_checkin_rejects_bad_rpe(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        resp = client.post(
            f'/api/training-plan/{plan}/checkin', json={'rpe_yesterday': 99}
        )
        assert resp.status_code == 400
        assert 'rpe_yesterday' in resp.get_json()['error']


def test_post_checkin_rejects_bad_feeling(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        resp = client.post(
            f'/api/training-plan/{plan}/checkin', json={'feeling': 'amazing'}
        )
        assert resp.status_code == 400


def test_post_checkin_rejects_empty_payload(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        resp = client.post(f'/api/training-plan/{plan}/checkin', json={})
        assert resp.status_code == 400


def test_get_today_checkin_returns_null_when_absent(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        resp = client.get(f'/api/training-plan/{plan}/checkin')
        assert resp.status_code == 200
        assert resp.get_json() == {'checkin': None}


def test_get_today_checkin_returns_row_when_present(app, user, auth_user, plan):
    with app.app_context():
        client = app.test_client()
        client.post(
            f'/api/training-plan/{plan}/checkin', json={'feeling': 'ok', 'sleep_h': 7.0}
        )
        resp = client.get(f'/api/training-plan/{plan}/checkin')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['checkin']['feeling'] == 'ok'


def test_post_checkin_404_on_other_users_plan(app, user, auth_user):
    """The check-in endpoint scopes the plan_id to the calling user."""
    with app.app_context():
        # Other user's plan.
        other = User(strava_user_id=8888, strava_username='other')
        db.session.add(other)
        db.session.commit()
        other_plan = TrainingPlan(
            user_id=other.id,
            plan_name='Other plan',
            status='active',
            weeks=[],
        )
        db.session.add(other_plan)
        db.session.commit()

        client = app.test_client()
        resp = client.post(
            f'/api/training-plan/{other_plan.id}/checkin', json={'feeling': 'good'}
        )
        assert resp.status_code == 404

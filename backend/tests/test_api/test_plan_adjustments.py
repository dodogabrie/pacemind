"""Tests for GET /api/training-plan/<id>/adjustments (coach-review #68)."""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import MagicMock, patch

from app import create_app
from database import db
from models import PlanAdjustment, TrainingPlan, User


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
        u = User(strava_user_id=5151, strava_username='adj-api-user')
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def auth_user(app, user):
    mock = MagicMock()
    mock.id = user
    with patch('api.training_plan.get_current_user', return_value=mock):
        yield mock


@pytest.fixture
def plan(app, user):
    with app.app_context():
        p = TrainingPlan(user_id=user, plan_name='Plan', status='active', weeks=[])
        db.session.add(p)
        db.session.commit()
        return p.id


def _adj(plan_id, user_id, applied_at, kind='swap'):
    row = PlanAdjustment(
        plan_id=plan_id, user_id=user_id, kind=kind, trigger='daily_checkin',
        day_before='Wednesday', day_after='Friday',
        workout_type_before='intervals', workout_type_after='recovery',
        applied_at=applied_at,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_lists_adjustments_most_recent_first(app, user, auth_user, plan):
    with app.app_context():
        base = datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc)
        _adj(plan, user, base)
        _adj(plan, user, base + timedelta(days=2), kind='downgrade')

        resp = app.test_client().get(f'/api/training-plan/{plan}/adjustments')
        assert resp.status_code == 200
        rows = resp.get_json()['adjustments']
        assert len(rows) == 2
        # Most-recent first.
        assert rows[0]['kind'] == 'downgrade'
        assert rows[1]['kind'] == 'swap'
        assert rows[1]['day_before'] == 'Wednesday'


def test_since_filter(app, user, auth_user, plan):
    with app.app_context():
        _adj(plan, user, datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc))
        _adj(plan, user, datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc))

        resp = app.test_client().get(
            f'/api/training-plan/{plan}/adjustments?since=2026-05-10'
        )
        assert resp.status_code == 200
        rows = resp.get_json()['adjustments']
        assert len(rows) == 1
        assert rows[0]['applied_at'].startswith('2026-05-20')


def test_bad_since_returns_400(app, user, auth_user, plan):
    with app.app_context():
        resp = app.test_client().get(
            f'/api/training-plan/{plan}/adjustments?since=not-a-date'
        )
        assert resp.status_code == 400


def test_404_on_other_users_plan(app, user, auth_user):
    with app.app_context():
        other = User(strava_user_id=6262, strava_username='other')
        db.session.add(other)
        db.session.commit()
        other_plan = TrainingPlan(user_id=other.id, plan_name='Other', status='active', weeks=[])
        db.session.add(other_plan)
        db.session.commit()

        resp = app.test_client().get(f'/api/training-plan/{other_plan.id}/adjustments')
        assert resp.status_code == 404


def test_401_when_unauthenticated(app, plan):
    with app.app_context():
        with patch('api.training_plan.get_current_user', return_value=None):
            resp = app.test_client().get(f'/api/training-plan/{plan}/adjustments')
            assert resp.status_code == 401

"""Tests for /api/training-plan/calendar endpoints."""

from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from database import db
from models import User
from models.training_plan import TrainingPlan
from services.personal_plan_service import PERSONAL_PLAN_NAME


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
        u = User(strava_user_id=999, strava_username='cal-api-user')
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


def _race_plan(user_id, weeks, race_date_iso, name='Race A', race_id=10):
    return TrainingPlan(
        user_id=user_id,
        plan_name=name,
        race_id=race_id,
        race_date=datetime.fromisoformat(race_date_iso),
        status='active',
        weeks=weeks,
    )


def test_calendar_get_aggregates_days_across_plans(app, user, auth_user):
    with app.app_context():
        race = _race_plan(user, [{
            'week_number': 1,
            'start_date': '2026-04-06',
            'days': [
                {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 8},
                {'day': 'Saturday', 'workout_type': 'long_run', 'distance_km': 25},
            ],
        }], race_date_iso='2026-04-19')
        db.session.add(race)
        db.session.commit()

        client = app.test_client()
        resp = client.get('/api/training-plan/calendar?from=2026-04-01&to=2026-04-30')
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body['days']) == 2
        dates = [d['date'] for d in body['days']]
        assert '2026-04-06' in dates
        assert '2026-04-11' in dates
        assert len(body['races']) == 1
        assert body['races'][0]['race_priority'] is None


def test_calendar_get_filters_outside_window(app, user, auth_user):
    with app.app_context():
        race = _race_plan(user, [{
            'week_number': 1,
            'start_date': '2026-04-06',
            'days': [
                {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 8},
            ],
        }], race_date_iso='2026-04-19')
        db.session.add(race)
        db.session.commit()

        client = app.test_client()
        resp = client.get('/api/training-plan/calendar?from=2026-05-01&to=2026-05-31')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['days'] == []
        assert body['races'] == []


def test_calendar_post_creates_personal_plan_when_no_match(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        # No plans yet -> POST should create the Personal plan and a week.
        resp = client.post('/api/training-plan/calendar/days', json={
            'date': '2026-05-12',
            'workout_type': 'easy',
            'title': 'Quick spin',
            'distance_km': 6,
        })
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['plan_name'] == PERSONAL_PLAN_NAME
        assert body['race_id'] is None
        assert body['day'] == 'Tuesday'
        assert body['date'] == '2026-05-12'

        # Plan should now exist with one week containing one day on Tuesday.
        plan = TrainingPlan.query.filter_by(user_id=user, plan_name=PERSONAL_PLAN_NAME).first()
        assert plan is not None
        assert len(plan.weeks) == 1
        week = plan.weeks[0]
        assert week['start_date'] == '2026-05-11'  # Monday of that week
        assert len(week['days']) == 1
        assert week['days'][0]['day'] == 'Tuesday'
        assert week['days'][0]['distance_km'] == 6


def test_calendar_post_routes_to_race_plan_when_window_matches(app, user, auth_user):
    with app.app_context():
        race = _race_plan(user, [{
            'week_number': 1,
            'start_date': '2026-04-06',
            'days': [],
        }], race_date_iso='2026-04-19')
        db.session.add(race)
        db.session.commit()

        client = app.test_client()
        resp = client.post('/api/training-plan/calendar/days', json={
            'date': '2026-04-10',
            'workout_type': 'tempo',
            'distance_km': 10,
        })
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['plan_id'] == race.id
        assert body['plan_name'] == 'Race A'

        db.session.refresh(race)
        days = race.weeks[0]['days']
        assert any(d['day'] == 'Friday' and d.get('distance_km') == 10 for d in days)


def test_calendar_post_idempotent_week_creation(app, user, auth_user):
    """Two adds in the same week must not create duplicate weeks."""
    with app.app_context():
        client = app.test_client()
        r1 = client.post('/api/training-plan/calendar/days', json={
            'date': '2026-05-12', 'workout_type': 'easy', 'distance_km': 5,
        })
        r2 = client.post('/api/training-plan/calendar/days', json={
            'date': '2026-05-15', 'workout_type': 'tempo', 'distance_km': 8,
        })
        assert r1.status_code == 200 and r2.status_code == 200

        plan = TrainingPlan.query.filter_by(user_id=user, plan_name=PERSONAL_PLAN_NAME).first()
        assert len(plan.weeks) == 1
        assert len(plan.weeks[0]['days']) == 2
        # Week totals updated
        assert plan.weeks[0]['total_km'] == 13.0


def test_calendar_post_rejects_invalid_date(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.post('/api/training-plan/calendar/days', json={'date': 'not-a-date'})
        assert resp.status_code == 400


def test_calendar_post_rejects_bad_steps(app, user, auth_user):
    with app.app_context():
        client = app.test_client()
        resp = client.post('/api/training-plan/calendar/days', json={
            'date': '2026-05-12',
            'steps': [{'type': 'work'}],  # missing measure -> invalid
        })
        assert resp.status_code == 400


def _move_plan(user):
    mon = date.today() + timedelta(days=7 - date.today().weekday())
    plan = TrainingPlan(user_id=user, plan_name=PERSONAL_PLAN_NAME, status='active', weeks=[{
        'week_number': 1, 'start_date': mon.isoformat(), 'total_km': 18, 'total_elevation_m': 0,
        'days': [
            {'day': 'Monday', 'date': mon.isoformat(), 'workout_type': 'easy', 'distance_km': 8,
             'route_id': 5, 'route_match_quality': 'exact', 'location_id': 2},
            {'day': 'Wednesday', 'date': (mon + timedelta(days=2)).isoformat(),
             'workout_type': 'tempo', 'distance_km': 10},
        ]}])
    db.session.add(plan)
    db.session.commit()
    return plan.id, mon


def test_calendar_move_empty_day_and_swap(app, user, auth_user):
    with app.app_context():
        pid, mon = _move_plan(user)
        c = app.test_client()
        tue, wed = mon + timedelta(days=1), mon + timedelta(days=2)
        assert c.post('/api/training-plan/calendar/move',
                      json={'from_date': mon.isoformat(), 'to_date': tue.isoformat()}).status_code == 200
        days = {d['day']: d for d in db.session.get(TrainingPlan, pid).weeks[0]['days']}
        assert days['Tuesday']['route_id'] == 5 and days['Tuesday']['location_id'] == 2
        assert days['Tuesday']['date'] == tue.isoformat()
        assert not days['Monday'].get('workout_type')
        assert c.post('/api/training-plan/calendar/move',
                      json={'from_date': tue.isoformat(), 'to_date': wed.isoformat()}).status_code == 200
        days = {d['day']: d for d in db.session.get(TrainingPlan, pid).weeks[0]['days']}
        assert days['Tuesday']['workout_type'] == 'tempo' and days['Wednesday']['workout_type'] == 'easy'


def test_calendar_move_rejects_past_date(app, user, auth_user):
    with app.app_context():
        _, mon = _move_plan(user)
        r = app.test_client().post('/api/training-plan/calendar/move', json={
            'from_date': mon.isoformat(), 'to_date': (date.today() - timedelta(days=1)).isoformat()})
        assert r.status_code == 400

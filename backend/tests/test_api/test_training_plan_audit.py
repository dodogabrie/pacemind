"""Audit tests for backend/api/training_plan.py — input validation gaps.

Covers Session 7 fixes:
  - update_workout_day numeric coercion (string distance_km used to crash
    week-totals sum() with TypeError → now returns 400).
  - update_pace_zones float() crashes (now 400 on bad type, validates
    min < max, validates zone_data is a dict).
  - update_preferences int()/float() crashes for strength_training_days
    and max_hours_per_day (now 400 instead of 500).
  - update_plan validates plan_name and weeks types.
  - export_ics filename sanitization (CRLF/quote injection in
    Content-Disposition).
  - get_dashboard race_countdown simplification.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import User
from models.training_plan import TrainingPlan


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
        u = User(strava_user_id=12345, strava_username='audit-user')
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def plan(app, user):
    with app.app_context():
        p = TrainingPlan(
            user_id=user,
            plan_name='Test Plan',
            weeks=[{
                'week_number': 1,
                'days': [
                    {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 5,
                     'duration_min': 30, 'elevation_m': 50, 'intensity': 1},
                    {'day': 'Tuesday', 'workout_type': 'rest', 'distance_km': 0},
                ],
                'total_km': 5,
                'total_elevation_m': 50,
            }],
            status='active',
        )
        db.session.add(p)
        db.session.commit()
        return p.id


@pytest.fixture
def auth_user(app, user):
    """Patch get_current_user to return the test user."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.id = user
    with patch('api.training_plan.get_current_user', return_value=mock):
        yield mock


# ---------- update_workout_day numeric validation ----------

def test_update_workout_day_rejects_string_distance(app, plan, auth_user):
    """Stringy distance_km used to be stored as-is, then crashed the
    week-totals sum() with TypeError. Now must return 400."""
    client = app.test_client()
    resp = client.patch(
        f'/api/training-plan/{plan}/weeks/1/days/Monday',
        json={'distance_km': 'ten'},
    )
    assert resp.status_code == 400
    assert 'distance_km' in resp.get_json()['error']


def test_update_workout_day_rejects_negative_distance(app, plan, auth_user):
    client = app.test_client()
    resp = client.patch(
        f'/api/training-plan/{plan}/weeks/1/days/Monday',
        json={'distance_km': -5},
    )
    assert resp.status_code == 400


def test_update_workout_day_rejects_out_of_range_duration(app, plan, auth_user):
    client = app.test_client()
    # 1440 is the upper bound (24h); 2000 should fail.
    resp = client.patch(
        f'/api/training-plan/{plan}/weeks/1/days/Monday',
        json={'duration_min': 2000},
    )
    assert resp.status_code == 400


def test_update_workout_day_accepts_valid_numeric(app, plan, auth_user):
    client = app.test_client()
    resp = client.patch(
        f'/api/training-plan/{plan}/weeks/1/days/Monday',
        json={'distance_km': 12.5, 'duration_min': 75, 'elevation_m': 200},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['day']['distance_km'] == 12.5
    # Week totals were recomputed without crashing.
    assert body['week_totals']['total_km'] == 12.5  # Tuesday is 0
    assert body['week_totals']['total_elevation_m'] == 200


# ---------- update_plan validation ----------

def test_update_plan_rejects_non_list_weeks(app, plan, auth_user):
    client = app.test_client()
    resp = client.put(f'/api/training-plan/{plan}', json={'weeks': 'oops'})
    assert resp.status_code == 400


def test_update_plan_rejects_empty_plan_name(app, plan, auth_user):
    client = app.test_client()
    resp = client.put(f'/api/training-plan/{plan}', json={'plan_name': '   '})
    assert resp.status_code == 400


def test_update_plan_rejects_non_string_plan_name(app, plan, auth_user):
    client = app.test_client()
    resp = client.put(f'/api/training-plan/{plan}', json={'plan_name': 12345})
    assert resp.status_code == 400


# ---------- update_pace_zones validation ----------

def test_update_pace_zones_rejects_non_dict_zones(app, auth_user):
    client = app.test_client()
    resp = client.put('/api/training-plan/pace-zones', json={'zones': 'flat'})
    assert resp.status_code == 400


def test_update_pace_zones_rejects_non_numeric_pace(app, auth_user):
    client = app.test_client()
    # Use a real ZONE_ORDER name so the loop body executes.
    from services.pace_zone_service import ZONE_ORDER
    zone_name = next(iter(ZONE_ORDER))
    resp = client.put('/api/training-plan/pace-zones', json={
        'zones': {zone_name: {'min_pace': 'fast', 'max_pace': 6.0}},
    })
    # Was 500 (raw ValueError from float()); now 400.
    assert resp.status_code == 400


def test_update_pace_zones_rejects_min_ge_max(app, auth_user):
    client = app.test_client()
    from services.pace_zone_service import ZONE_ORDER
    zone_name = next(iter(ZONE_ORDER))
    resp = client.put('/api/training-plan/pace-zones', json={
        'zones': {zone_name: {'min_pace': 6.0, 'max_pace': 4.0}},
    })
    assert resp.status_code == 400


# ---------- update_preferences validation ----------

def test_update_preferences_bad_strength_days_type_returns_400(app, auth_user):
    client = app.test_client()
    resp = client.put('/api/training-plan/preferences', json={
        'strength_training_days': 'two',
    })
    # Was 500 (ValueError from int()); now 400.
    assert resp.status_code == 400


def test_update_preferences_bad_max_hours_type_returns_400(app, auth_user):
    client = app.test_client()
    resp = client.put('/api/training-plan/preferences', json={
        'max_hours_per_day': 'three',
    })
    assert resp.status_code == 400


# ---------- export_ics filename sanitization ----------

def test_export_ics_filename_strips_crlf_and_quotes(app, user, auth_user):
    """A plan_name with CRLF or quotes used to land verbatim in the
    Content-Disposition header — header-injection vector. Must be sanitized."""
    with app.app_context():
        nasty = TrainingPlan(
            user_id=user,
            plan_name='evil"\r\nX-Injected: 1',
            weeks=[],
            status='active',
        )
        db.session.add(nasty)
        db.session.commit()
        plan_id = nasty.id

    client = app.test_client()
    with patch('services.calendar_export_service.generate_ics', return_value='BEGIN:VCALENDAR\nEND:VCALENDAR'):
        resp = client.get(f'/api/training-plan/{plan_id}/export/ics')
    assert resp.status_code == 200
    cd = resp.headers.get('Content-Disposition', '')
    assert '\r' not in cd and '\n' not in cd
    # The opening quote of the filename param should still be balanced —
    # i.e. there is exactly one un-escaped " before .ics.
    assert cd.count('"') == 2
    assert 'X-Injected' not in resp.headers


def test_export_ics_falls_back_when_name_is_whitespace(app, user, auth_user):
    """Whitespace-only plan_name (defensive — DB column is non-null but
    callers can stuff it with spaces) used to produce '.ics' as the
    filename, which is malformed. Now falls back to 'training_plan.ics'."""
    with app.app_context():
        weird = TrainingPlan(
            user_id=user,
            plan_name='   ',
            weeks=[],
            status='active',
        )
        db.session.add(weird)
        db.session.commit()
        plan_id = weird.id

    client = app.test_client()
    with patch('services.calendar_export_service.generate_ics', return_value='X'):
        resp = client.get(f'/api/training-plan/{plan_id}/export/ics')
    assert resp.status_code == 200
    cd = resp.headers.get('Content-Disposition', '')
    assert 'training_plan.ics' in cd


# ---------- get_dashboard race_countdown ----------

def test_get_dashboard_race_countdown_with_future_race(app, user, auth_user):
    """Past the cleanup, the conditional simplification still computes a
    correct non-negative countdown for a future race."""
    from datetime import timedelta
    with app.app_context():
        future = datetime.now(timezone.utc) + timedelta(days=42)
        p = TrainingPlan(
            user_id=user,
            plan_name='Future Race',
            weeks=[],
            race_date=future,
            status='active',
        )
        db.session.add(p)
        db.session.commit()
        plan_id = p.id

    client = app.test_client()
    # Stub out the heavy services that the dashboard calls.
    with patch('api.training_plan.PredictionRepository.get_latest_for_gpx', return_value=None), \
         patch('services.plan_compliance_service.PlanComplianceService.get_compliance_summary', return_value=None):
        resp = client.get(f'/api/training-plan/{plan_id}/dashboard')
    assert resp.status_code == 200
    body = resp.get_json()
    # Race is ~42 days out (allow ±1 for clock skew at the date boundary).
    assert 41 <= body['race_countdown'] <= 43


def test_get_dashboard_race_countdown_clamped_to_zero_for_past_race(app, user, auth_user):
    from datetime import timedelta
    with app.app_context():
        past = datetime.now(timezone.utc) - timedelta(days=10)
        p = TrainingPlan(
            user_id=user,
            plan_name='Past Race',
            weeks=[],
            race_date=past,
            status='completed',
        )
        db.session.add(p)
        db.session.commit()
        plan_id = p.id

    client = app.test_client()
    with patch('api.training_plan.PredictionRepository.get_latest_for_gpx', return_value=None), \
         patch('services.plan_compliance_service.PlanComplianceService.get_compliance_summary', return_value=None):
        resp = client.get(f'/api/training-plan/{plan_id}/dashboard')
    assert resp.status_code == 200
    assert resp.get_json()['race_countdown'] == 0

"""Tests for the sliding-window matching in PlanComplianceService.

Pre-existing behaviour: a planned workout matched only on the exact target
date — a long run shifted by a day was scored as "missed". This test suite
locks in:

  - exact-date match (Pass 1) keeps preceding semantics intact;
  - shifted workouts (±1 default, ±2 for long_run/race_simulation) get
    matched in Pass 2;
  - one Strava activity cannot be claimed by two planned workouts;
  - exact-date precedence: when both an exact-date and a windowed
    candidate exist for the same planned workout, exact-date wins.

Tests use sqlite-in-memory and the real repositories (no mocks).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import create_app
from database import db
from models import Activity, TrainingPlan, User, WorkoutCompletion
from services.plan_compliance_service import PlanComplianceService


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
        u = User(strava_user_id=9999, strava_username='sliding-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _make_plan(user_id: int, plan_start_monday: date, days: list) -> TrainingPlan:
    plan = TrainingPlan(
        user_id=user_id,
        plan_name='Sliding window plan',
        status='active',
        created_at=datetime.combine(plan_start_monday, datetime.min.time(), tzinfo=timezone.utc),
        weeks=[{
            'week_number': 1,
            'start_date': plan_start_monday.isoformat(),
            'days': days,
        }],
    )
    db.session.add(plan)
    db.session.commit()
    return plan


def _add_activity(user_id: int, when: date, distance_km: float, strava_id: int) -> Activity:
    act = Activity(
        user_id=user_id,
        strava_id=strava_id,
        name=f'Run on {when}',
        distance=distance_km * 1000,
        start_date=datetime.combine(when, datetime.min.time().replace(hour=8)),
    )
    db.session.add(act)
    db.session.commit()
    return act


def _completions(plan_id: int):
    return {(c.week_number, c.day): c
            for c in WorkoutCompletion.query.filter_by(plan_id=plan_id).all()}


# ---------------------------------------------------------------------------
# Pass 1 — exact date (back-compat)
# ---------------------------------------------------------------------------

def test_exact_date_match_still_works(app, user):
    """Pass 1: same-day match behaves as before window was introduced."""
    with app.app_context():
        # Use a past Monday so target_date is in the past relative to today.
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Tuesday', 'workout_type': 'easy', 'distance_km': 8},
        ])
        _add_activity(user, monday + timedelta(days=1), distance_km=8.0, strava_id=1001)

        PlanComplianceService().check_compliance(user, plan.id)

        c = _completions(plan.id)[(1, 'Tuesday')]
        assert c.strava_activity_id is not None
        assert c.status == 'completed'
        assert c.actual_distance_km == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Pass 2 — sliding window
# ---------------------------------------------------------------------------

def test_long_run_shifted_one_day_matches(app, user):
    """Long run planned Sunday, done Saturday → matched via window=2."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Sunday', 'workout_type': 'long_run', 'distance_km': 25},
        ])
        # Activity on Saturday — one day before planned Sunday LR.
        _add_activity(user, monday + timedelta(days=5), distance_km=24.5, strava_id=2001)

        PlanComplianceService().check_compliance(user, plan.id)

        c = _completions(plan.id)[(1, 'Sunday')]
        assert c.strava_activity_id is not None
        assert c.status in ('completed', 'partial')


def test_intervals_shifted_one_day_matches(app, user):
    """Intervals planned Tue, done Wed → matched via default window=1."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Tuesday', 'workout_type': 'intervals', 'distance_km': 10},
        ])
        _add_activity(user, monday + timedelta(days=2), distance_km=10.0, strava_id=2002)

        PlanComplianceService().check_compliance(user, plan.id)
        c = _completions(plan.id)[(1, 'Tuesday')]
        assert c.strava_activity_id is not None


def test_long_run_shifted_two_days_matches(app, user):
    """Long run planned Sunday, done Friday → still inside window=2."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Sunday', 'workout_type': 'long_run', 'distance_km': 25},
        ])
        # Friday — two days before planned Sunday.
        _add_activity(user, monday + timedelta(days=4), distance_km=24.0, strava_id=2003)

        PlanComplianceService().check_compliance(user, plan.id)
        c = _completions(plan.id)[(1, 'Sunday')]
        assert c.strava_activity_id is not None


def test_workout_shifted_two_days_is_missed(app, user):
    """Default window is 1 day. Non-LR workout shifted by 2 days stays missed."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Tuesday', 'workout_type': 'tempo', 'distance_km': 10},
        ])
        # Thursday — two days after planned Tuesday, beyond window=1.
        _add_activity(user, monday + timedelta(days=3), distance_km=10.0, strava_id=2004)

        PlanComplianceService().check_compliance(user, plan.id)
        c = _completions(plan.id)[(1, 'Tuesday')]
        assert c.strava_activity_id is None
        assert c.status == 'missed'


# ---------------------------------------------------------------------------
# No-double-match / exact-date precedence
# ---------------------------------------------------------------------------

def test_no_double_match_across_passes(app, user):
    """Two planned workouts with overlapping windows compete for one
    activity — that activity must be claimed only once."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            # Wed intervals @ 10km — slot match (exact-date).
            {'day': 'Wednesday', 'workout_type': 'intervals', 'distance_km': 10},
            # Sat long_run @ 22km — only a Thu activity exists nearby.
            {'day': 'Saturday', 'workout_type': 'long_run', 'distance_km': 22},
        ])
        # Wed activity (exact match for intervals).
        wed_act = _add_activity(user, monday + timedelta(days=2), distance_km=10.0, strava_id=3001)
        # Thu activity — falls in Sat long_run window=2 but should not steal
        # the Wed one even via cross-pass interaction.
        thu_act = _add_activity(user, monday + timedelta(days=3), distance_km=22.0, strava_id=3002)

        PlanComplianceService().check_compliance(user, plan.id)
        comps = _completions(plan.id)
        assert comps[(1, 'Wednesday')].strava_activity_id == wed_act.id
        assert comps[(1, 'Saturday')].strava_activity_id == thu_act.id


def test_exact_date_precedence_over_windowed(app, user):
    """When both an exact-date and a windowed candidate exist, exact-date wins."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            {'day': 'Tuesday', 'workout_type': 'tempo', 'distance_km': 10},
        ])
        # Tuesday exact match.
        exact = _add_activity(user, monday + timedelta(days=1), distance_km=10.0, strava_id=4001)
        # Wednesday windowed candidate.
        _add_activity(user, monday + timedelta(days=2), distance_km=10.0, strava_id=4002)

        PlanComplianceService().check_compliance(user, plan.id)
        c = _completions(plan.id)[(1, 'Tuesday')]
        assert c.strava_activity_id == exact.id


def test_window_does_not_reclaim_already_matched_activity(app, user):
    """An activity already claimed in Pass 1 cannot be re-used in Pass 2,
    even if it'd be the best windowed candidate for another workout."""
    with app.app_context():
        monday = date.today() - timedelta(days=date.today().weekday(), weeks=2)
        plan = _make_plan(user, monday, [
            # Wed tempo — will exact-match.
            {'day': 'Wednesday', 'workout_type': 'tempo', 'distance_km': 8},
            # Thu intervals — no exact match; Wed activity is window=1
            # away. Must not be reclaimed.
            {'day': 'Thursday', 'workout_type': 'intervals', 'distance_km': 8},
        ])
        wed_act = _add_activity(user, monday + timedelta(days=2), distance_km=8.0, strava_id=5001)

        PlanComplianceService().check_compliance(user, plan.id)
        comps = _completions(plan.id)
        assert comps[(1, 'Wednesday')].strava_activity_id == wed_act.id
        assert comps[(1, 'Thursday')].strava_activity_id is None
        assert comps[(1, 'Thursday')].status == 'missed'

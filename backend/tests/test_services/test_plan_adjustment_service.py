"""Tests for plan_adjustment_service.PlanAdjustmentService.

Covers the two coach-review #55 rules:

  R1. A bad check-in on a quality day swaps that day's workout with the
      easiest remaining day later in the same week (calendar slots stay
      put — only the workout payload moves).
  R2. Two consecutive bad days downgrade the next quality session within
      a 3-day horizon (intervals/tempo/etc. → easy).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import create_app
from database import db
from models import DailyCheckin, TrainingPlan, User
from services.plan_adjustment_service import PlanAdjustmentService


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
        u = User(strava_user_id=4242, strava_username='checkin-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _make_plan(user_id: int, today: date, today_workout_type: str = 'intervals',
               include_easier_later: bool = True) -> TrainingPlan:
    """Build a 1-week plan anchored to today (Monday of this week).

    today: which calendar date the run-of-interest is on.
    Week layout: Mon=easy, Tue=tempo (or supplied), Wed=intervals, Thu=easy,
                 Fri=recovery, Sat=easy_pickups, Sun=long_run.
    The day at ``today`` is rewritten to use ``today_workout_type``.
    """
    monday = today - timedelta(days=today.weekday())
    days = []
    base = [
        ('Monday', 'easy', 8),
        ('Tuesday', 'easy', 8),
        ('Wednesday', 'easy', 10),
        ('Thursday', 'easy', 8),
        ('Friday', 'recovery', 5),
        ('Saturday', 'easy_pickups', 6),
        ('Sunday', 'long_run', 25),
    ]
    today_idx = today.weekday()
    base[today_idx] = (base[today_idx][0], today_workout_type, 10)
    if not include_easier_later:
        # Remove all easier days after today (force the swap to fail).
        for i in range(today_idx + 1, 7):
            base[i] = (base[i][0], 'tempo', 10)  # all hard
    for name, wt, km in base:
        days.append({'day': name, 'workout_type': wt, 'distance_km': km})
    plan = TrainingPlan(
        user_id=user_id,
        plan_name='Test plan',
        status='active',
        created_at=datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc),
        weeks=[{
            'week_number': 1,
            'start_date': monday.isoformat(),
            'days': days,
        }],
    )
    db.session.add(plan)
    db.session.commit()
    return plan


def _make_checkin(user_id: int, day: date, *, is_bad: bool) -> DailyCheckin:
    c = DailyCheckin(
        user_id=user_id,
        date=day,
        feeling='bad' if is_bad else 'good',
        rpe_yesterday=9 if is_bad else 4,
        sleep_h=4.5 if is_bad else 8.0,
        soreness=8 if is_bad else 2,
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_bad_checkin_swaps_today_quality_with_easiest_later_day(app, user):
    """R1: bad day + intervals today → swap with the easiest remaining day."""
    with app.app_context():
        # Anchor on a Wednesday so there's clearly an easier later day (Fri=recovery).
        today = date(2026, 5, 20)  # Wednesday
        plan = _make_plan(user, today, today_workout_type='intervals')
        _make_checkin(user, today, is_bad=True)

        result = PlanAdjustmentService().apply_for_user(user, today=today)

        assert len(result['adjusted']) == 1
        change = result['adjusted'][0]['changes'][0]
        assert change['kind'] == 'swap'
        assert change['today_day'] == 'Wednesday'
        # Recovery is the easiest available later day this week (Fri).
        assert change['moved_to_day'] == 'Friday'

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        # Workouts swapped; calendar slots preserved.
        assert days['Wednesday']['workout_type'] == 'recovery'
        assert days['Friday']['workout_type'] == 'intervals'


def test_easy_today_no_swap(app, user):
    """Already easy today → no adjustment needed."""
    with app.app_context():
        today = date(2026, 5, 20)
        plan = _make_plan(user, today, today_workout_type='easy')
        _make_checkin(user, today, is_bad=True)

        result = PlanAdjustmentService().apply_for_user(user, today=today)
        assert result['adjusted'] == []

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        assert days['Wednesday']['workout_type'] == 'easy'


def test_good_checkin_no_adjustment(app, user):
    """Good day on a quality session → no swap."""
    with app.app_context():
        today = date(2026, 5, 20)
        plan = _make_plan(user, today, today_workout_type='intervals')
        _make_checkin(user, today, is_bad=False)

        result = PlanAdjustmentService().apply_for_user(user, today=today)
        assert result['adjusted'] == []

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        assert days['Wednesday']['workout_type'] == 'intervals'


def test_no_easier_day_left_in_week_leaves_plan_unchanged(app, user):
    """R1 cannot find a swap target → plan untouched, no exception."""
    with app.app_context():
        # Saturday today, with no easier day available later (Sunday is LR
        # which is intentionally not a swap target).
        today = date(2026, 5, 23)  # Saturday
        _make_plan(user, today, today_workout_type='intervals',
                   include_easier_later=False)
        _make_checkin(user, today, is_bad=True)

        result = PlanAdjustmentService().apply_for_user(user, today=today)
        # Swap fails (no candidate). No downgrade either (only one bad day).
        assert result['adjusted'] == []


def test_two_bad_days_downgrade_next_quality(app, user):
    """R2: two consecutive bad days → next quality session within 3 days
    is downgraded to easy."""
    with app.app_context():
        today = date(2026, 5, 21)  # Thursday — easy day
        yesterday = today - timedelta(days=1)
        # Plan: Thursday easy (no swap), Friday recovery, Saturday tempo
        # (the next quality session within horizon).
        monday = today - timedelta(days=today.weekday())
        plan = TrainingPlan(
            user_id=user,
            plan_name='Two-bad-days plan',
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
                    {'day': 'Friday', 'workout_type': 'recovery'},
                    {'day': 'Saturday', 'workout_type': 'tempo',
                     'title': 'Tempo run', 'steps': [{'duration_min': 20}]},
                    {'day': 'Sunday', 'workout_type': 'long_run'},
                ],
            }],
        )
        db.session.add(plan)
        db.session.commit()

        _make_checkin(user, yesterday, is_bad=True)
        _make_checkin(user, today, is_bad=True)

        result = PlanAdjustmentService().apply_for_user(user, today=today)
        adjustments = result['adjusted']
        assert len(adjustments) == 1
        changes = adjustments[0]['changes']
        kinds = [c['kind'] for c in changes]
        assert 'downgrade' in kinds

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        # Saturday tempo was the next quality within 3 days → downgraded.
        assert days['Saturday']['workout_type'] == 'easy'
        # Intensity-specific fields stripped.
        assert 'steps' not in days['Saturday']


def test_long_run_is_not_downgraded(app, user):
    """R2: the long_run is never downgraded — it's the aerobic spine.

    Only intensity (tempo/intervals/etc.) is softened; LR moves via R1's
    swap or stays untouched.
    """
    with app.app_context():
        today = date(2026, 5, 22)  # Friday
        yesterday = today - timedelta(days=1)
        monday = today - timedelta(days=today.weekday())
        plan = TrainingPlan(
            user_id=user,
            plan_name='LR is sacred',
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
                    {'day': 'Sunday', 'workout_type': 'long_run',
                     'distance_km': 30},
                ],
            }],
        )
        db.session.add(plan)
        db.session.commit()

        _make_checkin(user, yesterday, is_bad=True)
        _make_checkin(user, today, is_bad=True)

        PlanAdjustmentService().apply_for_user(user, today=today)
        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        # LR untouched.
        assert days['Sunday']['workout_type'] == 'long_run'
        assert days['Sunday']['distance_km'] == 30


def test_no_checkin_today_is_noop(app, user):
    """No check-in *and* no passive signal → service returns cleanly.

    The user has no Strava activity history in this test, so
    PassiveReadinessService falls back to ``None`` (TSB unreliable on
    cold-start) and the service reports ``no_signal``.
    """
    with app.app_context():
        today = date(2026, 5, 20)
        _make_plan(user, today, today_workout_type='intervals')
        result = PlanAdjustmentService().apply_for_user(user, today=today)
        assert result == {'adjusted': [], 'reason': 'no_signal'}


def test_idempotent_second_call_is_noop(app, user):
    """After a swap, calling again with the same check-in does nothing
    (today is now ``recovery``, no longer a quality day)."""
    with app.app_context():
        today = date(2026, 5, 20)
        _make_plan(user, today, today_workout_type='intervals')
        _make_checkin(user, today, is_bad=True)

        first = PlanAdjustmentService().apply_for_user(user, today=today)
        assert len(first['adjusted']) == 1

        second = PlanAdjustmentService().apply_for_user(user, today=today)
        assert second['adjusted'] == []

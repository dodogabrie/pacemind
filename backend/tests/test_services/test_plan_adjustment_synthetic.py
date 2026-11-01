"""Tests for the PassiveReadinessService integration in PlanAdjustmentService.

When the user skips the daily check-in, the service should fall back to a
synthetic checkin derived from TSB and still trigger the *swap* rule. The
*downgrade* rule must NOT fire on synthetic signals — a TSB-driven false
positive there is too expensive to undo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import DailyCheckin, TrainingPlan, User
from services.passive_readiness_service import SyntheticCheckin
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
        u = User(strava_user_id=4343, strava_username='synthetic-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _make_quality_plan(user_id: int, today: date) -> TrainingPlan:
    """Wed=intervals (today), Fri=recovery (easiest later)."""
    monday = today - timedelta(days=today.weekday())
    days = [
        {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 8},
        {'day': 'Tuesday', 'workout_type': 'easy', 'distance_km': 8},
        {'day': 'Wednesday', 'workout_type': 'intervals', 'distance_km': 10},
        {'day': 'Thursday', 'workout_type': 'easy', 'distance_km': 8},
        {'day': 'Friday', 'workout_type': 'recovery', 'distance_km': 5},
        {'day': 'Saturday', 'workout_type': 'easy_pickups', 'distance_km': 6},
        {'day': 'Sunday', 'workout_type': 'long_run', 'distance_km': 25},
    ]
    plan = TrainingPlan(
        user_id=user_id,
        plan_name='Synthetic-aware plan',
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


def test_synthetic_checkin_triggers_swap(app, user):
    """No DailyCheckin + low TSB → synthetic bad-day → quality swapped."""
    with app.app_context():
        today = date(2026, 5, 20)  # Wednesday
        plan = _make_quality_plan(user, today)

        synthetic = SyntheticCheckin(is_bad_day=True, source='tsb_low', confidence=0.8)
        with patch(
            'services.passive_readiness_service.PassiveReadinessService.compute_synthetic_checkin',
            return_value=synthetic,
        ):
            result = PlanAdjustmentService().apply_for_user(user, today=today)

        assert len(result['adjusted']) == 1
        adj = result['adjusted'][0]
        assert adj['source'] == 'synthetic'
        change = adj['changes'][0]
        assert change['kind'] == 'swap'
        assert change['today_day'] == 'Wednesday'
        assert change['moved_to_day'] == 'Friday'

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        assert days['Wednesday']['workout_type'] == 'recovery'
        assert days['Friday']['workout_type'] == 'intervals'


def test_synthetic_checkin_does_not_trigger_downgrade(app, user):
    """Even with yesterday's checkin = bad, a synthetic today must NOT
    fire the downgrade rule — only the (reversible) swap.

    Setup: Tue is intervals → swap candidate. Sat is tempo (future quality
    within 3 days from Wed). If we wrongly counted synthetic as a real
    bad day, Sat tempo would get downgraded; we assert it stays intact.
    """
    with app.app_context():
        today = date(2026, 5, 20)  # Wednesday
        yesterday = today - timedelta(days=1)
        monday = today - timedelta(days=today.weekday())
        plan = TrainingPlan(
            user_id=user,
            plan_name='Downgrade-guard plan',
            status='active',
            created_at=datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc),
            weeks=[{
                'week_number': 1,
                'start_date': monday.isoformat(),
                'days': [
                    {'day': 'Monday', 'workout_type': 'easy'},
                    {'day': 'Tuesday', 'workout_type': 'easy'},
                    {'day': 'Wednesday', 'workout_type': 'intervals'},
                    {'day': 'Thursday', 'workout_type': 'easy'},
                    {'day': 'Friday', 'workout_type': 'recovery'},
                    {'day': 'Saturday', 'workout_type': 'tempo',
                     'title': 'Tempo run', 'steps': [{'duration_min': 20}]},
                    {'day': 'Sunday', 'workout_type': 'long_run'},
                ],
            }],
        )
        db.session.add(plan)
        # Yesterday's check-in IS real and bad — but today's is synthetic,
        # so the two-bad-days gate should reject the combination.
        db.session.add(DailyCheckin(
            user_id=user, date=yesterday,
            feeling='bad', rpe_yesterday=9, sleep_h=4.0, soreness=8,
        ))
        db.session.commit()

        synthetic = SyntheticCheckin(is_bad_day=True, source='tsb_low', confidence=0.7)
        with patch(
            'services.passive_readiness_service.PassiveReadinessService.compute_synthetic_checkin',
            return_value=synthetic,
        ):
            result = PlanAdjustmentService().apply_for_user(user, today=today)

        kinds = [c['kind'] for c in result['adjusted'][0]['changes']]
        assert 'swap' in kinds
        assert 'downgrade' not in kinds  # ← the critical assertion

        db.session.refresh(plan)
        days = {d['day']: d for d in plan.weeks[0]['days']}
        # Saturday's tempo is preserved — no synthetic downgrade.
        assert days['Saturday']['workout_type'] == 'tempo'
        assert days['Saturday'].get('steps') == [{'duration_min': 20}]


def test_real_checkin_still_supports_downgrade(app, user):
    """Sanity check: the existing downgrade rule (two real bad days) keeps
    working — synthetic_used path doesn't accidentally short-circuit it."""
    with app.app_context():
        today = date(2026, 5, 21)  # Thursday
        yesterday = today - timedelta(days=1)
        monday = today - timedelta(days=today.weekday())
        plan = TrainingPlan(
            user_id=user,
            plan_name='Two real bad days',
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
        for d in (yesterday, today):
            db.session.add(DailyCheckin(
                user_id=user, date=d,
                feeling='bad', rpe_yesterday=9, sleep_h=4.0, soreness=8,
            ))
        db.session.commit()

        result = PlanAdjustmentService().apply_for_user(user, today=today)
        kinds = [c['kind'] for c in result['adjusted'][0]['changes']]
        assert 'downgrade' in kinds
        assert result['adjusted'][0]['source'] == 'manual'


def test_synthetic_returns_none_yields_no_signal(app, user):
    """PassiveReadinessService.None + no real check-in → no_signal, no error."""
    with app.app_context():
        today = date(2026, 5, 20)
        _make_quality_plan(user, today)
        with patch(
            'services.passive_readiness_service.PassiveReadinessService.compute_synthetic_checkin',
            return_value=None,
        ):
            result = PlanAdjustmentService().apply_for_user(user, today=today)
        assert result == {'adjusted': [], 'reason': 'no_signal'}

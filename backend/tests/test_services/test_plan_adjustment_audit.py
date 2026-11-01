"""Tests for the structured audit trail (coach-review #68).

Every applied swap/downgrade should write one ``PlanAdjustment`` row,
joinable to the plan and (for real check-ins) to the DailyCheckin, with a
before/after payload for replay.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import DailyCheckin, PlanAdjustment, TrainingPlan, User
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
        u = User(strava_user_id=9191, strava_username='audit-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _plan(user_id: int, today: date, days: list) -> TrainingPlan:
    monday = today - timedelta(days=today.weekday())
    plan = TrainingPlan(
        user_id=user_id,
        plan_name='Audit plan',
        status='active',
        created_at=datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc),
        weeks=[{'week_number': 1, 'start_date': monday.isoformat(), 'days': days}],
    )
    db.session.add(plan)
    db.session.commit()
    return plan


def _checkin(user_id: int, day: date, *, is_bad: bool) -> DailyCheckin:
    c = DailyCheckin(
        user_id=user_id, date=day,
        feeling='bad' if is_bad else 'good',
        rpe_yesterday=9 if is_bad else 4,
        sleep_h=4.5 if is_bad else 8.0,
        soreness=8 if is_bad else 2,
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_swap_writes_audit_row(app, user):
    with app.app_context():
        today = date(2026, 5, 20)  # Wednesday
        plan = _plan(user, today, [
            {'day': 'Monday', 'workout_type': 'easy'},
            {'day': 'Tuesday', 'workout_type': 'easy'},
            {'day': 'Wednesday', 'workout_type': 'intervals'},
            {'day': 'Thursday', 'workout_type': 'easy'},
            {'day': 'Friday', 'workout_type': 'recovery'},
            {'day': 'Saturday', 'workout_type': 'easy'},
            {'day': 'Sunday', 'workout_type': 'long_run'},
        ])
        checkin = _checkin(user, today, is_bad=True)

        PlanAdjustmentService().apply_for_user(user, today=today)

        rows = PlanAdjustment.query.filter_by(plan_id=plan.id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.kind == 'swap'
        assert row.trigger == 'daily_checkin'
        assert row.day_before == 'Wednesday'
        assert row.day_after == 'Friday'
        assert row.workout_type_before == 'intervals'
        assert row.workout_type_after == 'recovery'
        assert row.checkin_id == checkin.id
        # Payload carries full before/after for replay.
        assert row.payload_json['before']['today']['workout_type'] == 'intervals'
        assert row.payload_json['after']['today']['workout_type'] == 'recovery'


def test_downgrade_writes_audit_row(app, user):
    with app.app_context():
        today = date(2026, 5, 21)  # Thursday (easy — no swap)
        yesterday = today - timedelta(days=1)
        plan = _plan(user, today, [
            {'day': 'Monday', 'workout_type': 'easy'},
            {'day': 'Tuesday', 'workout_type': 'easy'},
            {'day': 'Wednesday', 'workout_type': 'easy'},
            {'day': 'Thursday', 'workout_type': 'easy'},
            {'day': 'Friday', 'workout_type': 'recovery'},
            {'day': 'Saturday', 'workout_type': 'tempo',
             'title': 'Tempo run', 'steps': [{'duration_min': 20}]},
            {'day': 'Sunday', 'workout_type': 'long_run'},
        ])
        _checkin(user, yesterday, is_bad=True)
        _checkin(user, today, is_bad=True)

        PlanAdjustmentService().apply_for_user(user, today=today)

        rows = PlanAdjustment.query.filter_by(plan_id=plan.id, kind='downgrade').all()
        assert len(rows) == 1
        row = rows[0]
        assert row.trigger == 'daily_checkin'
        assert row.day_before == row.day_after == 'Saturday'
        assert row.workout_type_before == 'tempo'
        assert row.workout_type_after == 'easy'
        assert row.payload_json['before']['workout_type'] == 'tempo'
        assert row.payload_json['after']['workout_type'] == 'easy'


def test_no_adjustment_writes_no_row(app, user):
    with app.app_context():
        today = date(2026, 5, 20)
        plan = _plan(user, today, [
            {'day': 'Monday', 'workout_type': 'easy'},
            {'day': 'Tuesday', 'workout_type': 'easy'},
            {'day': 'Wednesday', 'workout_type': 'intervals'},
            {'day': 'Thursday', 'workout_type': 'easy'},
            {'day': 'Friday', 'workout_type': 'recovery'},
            {'day': 'Saturday', 'workout_type': 'easy'},
            {'day': 'Sunday', 'workout_type': 'long_run'},
        ])
        _checkin(user, today, is_bad=False)  # good day → no change

        PlanAdjustmentService().apply_for_user(user, today=today)
        assert PlanAdjustment.query.filter_by(plan_id=plan.id).count() == 0


def test_synthetic_signal_records_tsb_trigger_without_checkin(app, user):
    """A passive (TSB-driven) swap is logged with trigger='tsb' and no
    checkin_id — there is no DailyCheckin row behind it."""
    with app.app_context():
        today = date(2026, 5, 20)  # Wednesday
        plan = _plan(user, today, [
            {'day': 'Monday', 'workout_type': 'easy'},
            {'day': 'Tuesday', 'workout_type': 'easy'},
            {'day': 'Wednesday', 'workout_type': 'intervals'},
            {'day': 'Thursday', 'workout_type': 'easy'},
            {'day': 'Friday', 'workout_type': 'recovery'},
            {'day': 'Saturday', 'workout_type': 'easy'},
            {'day': 'Sunday', 'workout_type': 'long_run'},
        ])
        synthetic = SyntheticCheckin(is_bad_day=True, source='tsb_low')
        with patch(
            'services.passive_readiness_service.PassiveReadinessService.compute_synthetic_checkin',
            return_value=synthetic,
        ):
            PlanAdjustmentService().apply_for_user(user, today=today)

        rows = PlanAdjustment.query.filter_by(plan_id=plan.id).all()
        assert len(rows) == 1
        assert rows[0].trigger == 'tsb'
        assert rows[0].checkin_id is None
        assert rows[0].kind == 'swap'

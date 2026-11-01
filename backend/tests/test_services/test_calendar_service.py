"""Tests for backend/services/calendar_service.py."""

from datetime import date, datetime, timezone

import pytest

from app import create_app
from database import db
from models import User
from models.training_plan import TrainingPlan
from services.calendar_service import plan_covers, plan_window, resolve_target_plan
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
        u = User(strava_user_id=7, strava_username='cal-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _race_plan(user_id, weeks_starts, race_date_iso, plan_name='Race A', race_id=42):
    weeks = [{'week_number': i + 1, 'start_date': s, 'days': []} for i, s in enumerate(weeks_starts)]
    return TrainingPlan(
        user_id=user_id,
        plan_name=plan_name,
        race_id=race_id,
        race_date=datetime.fromisoformat(race_date_iso),
        status='active',
        weeks=weeks,
    )


def test_plan_window_uses_first_week_and_race_date(app, user):
    with app.app_context():
        p = _race_plan(user, ['2026-04-06', '2026-04-13'], '2026-04-19')
        start, end = plan_window(p)
        assert start == date(2026, 4, 6)
        assert end == date(2026, 4, 19)


def test_plan_covers_inside_window(app, user):
    with app.app_context():
        p = _race_plan(user, ['2026-04-06'], '2026-04-19')
        assert plan_covers(p, date(2026, 4, 10))
        assert not plan_covers(p, date(2026, 4, 5))
        assert not plan_covers(p, date(2026, 4, 20))


def test_resolve_prefers_race_plan_when_window_matches(app, user):
    with app.app_context():
        race = _race_plan(user, ['2026-04-06', '2026-04-13'], '2026-04-19')
        db.session.add(race)
        db.session.commit()

        target = resolve_target_plan(user, date(2026, 4, 10))
        assert target.id == race.id
        assert target.plan_name == 'Race A'


def test_resolve_falls_back_to_personal_plan_outside_race_window(app, user):
    with app.app_context():
        race = _race_plan(user, ['2026-04-06'], '2026-04-19')
        db.session.add(race)
        db.session.commit()

        target = resolve_target_plan(user, date(2026, 6, 1))
        assert target.race_id is None
        assert target.plan_name == PERSONAL_PLAN_NAME


def test_resolve_creates_personal_when_no_plans_exist(app, user):
    with app.app_context():
        target = resolve_target_plan(user, date(2026, 5, 1))
        assert target.plan_name == PERSONAL_PLAN_NAME
        assert target.race_id is None


def test_resolve_picks_earliest_race_when_multiple_match(app, user):
    with app.app_context():
        early = _race_plan(user, ['2026-04-06'], '2026-04-19', plan_name='Early', race_id=1)
        late = _race_plan(user, ['2026-04-06'], '2026-04-25', plan_name='Late', race_id=2)
        db.session.add_all([early, late])
        db.session.commit()

        target = resolve_target_plan(user, date(2026, 4, 10))
        assert target.plan_name == 'Early'


def test_resolve_ignores_completed_plans(app, user):
    with app.app_context():
        race = _race_plan(user, ['2026-04-06'], '2026-04-19')
        race.status = 'completed'
        db.session.add(race)
        db.session.commit()

        target = resolve_target_plan(user, date(2026, 4, 10))
        assert target.race_id is None
        assert target.plan_name == PERSONAL_PLAN_NAME

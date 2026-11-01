"""Tests for backend/services/personal_plan_service.py."""

import pytest

from app import create_app
from database import db
from models import User
from models.training_plan import TrainingPlan
from services.personal_plan_service import (
    PERSONAL_PLAN_NAME,
    get_or_create_personal_plan,
)


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
        u = User(strava_user_id=42, strava_username='pp-user')
        db.session.add(u)
        db.session.commit()
        return u.id


def test_creates_personal_plan_on_first_call(app, user):
    with app.app_context():
        plan = get_or_create_personal_plan(user)
        assert plan is not None
        assert plan.plan_name == PERSONAL_PLAN_NAME
        assert plan.race_id is None
        assert plan.race_date is None
        assert plan.status == 'active'
        assert plan.weeks == []


def test_idempotent_returns_same_plan(app, user):
    with app.app_context():
        first = get_or_create_personal_plan(user)
        first_id = first.id
        db.session.commit()
        second = get_or_create_personal_plan(user)
        assert second.id == first_id
        # And only one personal plan should exist for this user.
        all_personal = TrainingPlan.query.filter_by(
            user_id=user, race_id=None, plan_name=PERSONAL_PLAN_NAME
        ).all()
        assert len(all_personal) == 1


def test_does_not_clash_with_race_plans(app, user):
    """A race-targeted plan with race_id set must not be picked up as the
    personal plan."""
    with app.app_context():
        race_plan = TrainingPlan(
            user_id=user,
            plan_name='UTMB Plan',
            race_id=999,
            status='active',
            weeks=[],
        )
        db.session.add(race_plan)
        db.session.commit()

        personal = get_or_create_personal_plan(user)
        assert personal.id != race_plan.id
        assert personal.plan_name == PERSONAL_PLAN_NAME

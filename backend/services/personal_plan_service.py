"""Personal training plan helper.

Each user has at most one auto-managed "Personal" TrainingPlan: a plan with
no race_id, holding manually-added workouts that are not part of any
race-targeted plan. Idempotent: callers always get the same plan back.
"""

from datetime import datetime, timezone

from database import db
from models import TrainingPlan


PERSONAL_PLAN_NAME = 'Personal'


def get_or_create_personal_plan(user_id: int) -> TrainingPlan:
    """Return the user's personal plan, creating it on first call.

    The personal plan has no race_id, status='active' and starts with an
    empty weeks list. Callers append weeks/days as users add workouts.
    """
    plan = TrainingPlan.query.filter_by(
        user_id=user_id,
        race_id=None,
        plan_name=PERSONAL_PLAN_NAME,
    ).first()
    if plan is not None:
        return plan

    plan = TrainingPlan(
        user_id=user_id,
        plan_name=PERSONAL_PLAN_NAME,
        race_id=None,
        race_date=None,
        race_priority=None,
        weeks=[],
        status='active',
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(plan)
    db.session.flush()
    return plan

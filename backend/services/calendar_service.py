"""Calendar service: routes calendar operations to the right plan.

The calendar surface aggregates days across all the user's TrainingPlans.
When a user manually adds a workout on a date, we need to decide which plan
it belongs to:

  1. If an active race plan's window covers that date, use the race plan.
  2. Otherwise, use the user's auto-managed Personal plan.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from models import TrainingPlan
from services.personal_plan_service import get_or_create_personal_plan


def _parse_iso_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def plan_window(plan: TrainingPlan) -> Tuple[Optional[date], Optional[date]]:
    """Return (start_date, end_date) covering all workouts in the plan.

    Start = first week's start_date (falls back to plan.created_at).
    End = race_date or last week's start_date + 6 days. None if undetermined.
    """
    weeks = plan.weeks or []
    start: Optional[date] = None
    if weeks:
        start = _parse_iso_date(weeks[0].get('start_date'))
    if start is None and plan.created_at:
        start = _parse_iso_date(plan.created_at)

    end: Optional[date] = _parse_iso_date(plan.race_date)
    if end is None and weeks:
        last = _parse_iso_date(weeks[-1].get('start_date'))
        if last is not None:
            end = last + timedelta(days=6)

    return start, end


def plan_covers(plan: TrainingPlan, target: date) -> bool:
    start, end = plan_window(plan)
    if start is None or end is None:
        return False
    return start <= target <= end


def resolve_target_plan(user_id: int, target: date) -> TrainingPlan:
    """Pick the plan a manual workout on `target` should land on.

    Order:
      1. Active race plan (race_id IS NOT NULL) whose window covers `target`.
         If multiple match, prefer earliest race_date.
      2. The user's Personal plan (created on demand).
    """
    candidates: List[TrainingPlan] = TrainingPlan.query.filter(
        TrainingPlan.user_id == user_id,
        TrainingPlan.status == 'active',
        TrainingPlan.race_id.isnot(None),
    ).all()

    matching = [p for p in candidates if plan_covers(p, target)]
    if matching:
        matching.sort(
            key=lambda p: _parse_iso_date(p.race_date) or date.max
        )
        return matching[0]

    return get_or_create_personal_plan(user_id)

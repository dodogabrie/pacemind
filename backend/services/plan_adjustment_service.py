"""Plan adjustment service - readiness-aware re-shuffling of the upcoming week.

Drives the daily-checkin feedback loop (GH issue coach-review #55):

  - If today's check-in is "bad" (high RPE yesterday, bad feeling, short sleep,
    high soreness) and today is a quality session, swap today's workout with
    the easiest remaining day in the same week.

  - If the last two checkins are both bad and the next quality session is
    within 3 days, downgrade that quality session — tempo/intervals become
    ``easy``, descent_session becomes ``recovery`` — to protect the athlete
    from a third stressor in a row.

Adjustments are idempotent: re-running the service after a swap is a no-op.
They are also surfaced via NotificationService so the user knows their plan
changed.

Citations:
  - Foster, C. (1998). Monitoring training in athletes with reference to
    overtraining syndrome. Med Sci Sports Exerc.
  - Saw, A. E. et al. (2016). Monitoring the athlete training response.
    Br J Sports Med — subjective measures outperform objective ones.
  - Halson, S. L. (2014). Monitoring training load to understand fatigue in
    athletes. Sports Med.
"""

from __future__ import annotations

import copy
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from repositories import (
    DailyCheckinRepository,
    PlanAdjustmentRepository,
    TrainingPlanRepository,
)

logger = logging.getLogger(__name__)

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# Quality (hard) workouts whose timing matters most. Mirrors plan_engine's
# HARD_WORKOUTS plus long_run / race_simulation — kept local to avoid a
# circular import on plan_engine.
QUALITY_TYPES = {
    'intervals', 'hill_repeats', 'vert_session', 'tempo',
    'descent_session', 'long_run', 'race_simulation',
}

# Workouts safe to swap *into* today's slot when readiness is low. ``rest``
# is intentionally excluded — we move work around, we don't delete it.
EASY_SWAP_TYPES = {'easy', 'easy_pickups', 'easy_strides', 'recovery'}

# Downgrade targets for the "two bad days in a row" rule. Preserves volume
# but strips intensity. Mirrors plan_engine.MOUNTAIN_DOWNGRADE intent.
DOWNGRADE_MAP = {
    'intervals': 'easy',
    'tempo': 'easy',
    'hill_repeats': 'easy',
    'vert_session': 'easy',
    'descent_session': 'recovery',
    # long_run intentionally NOT downgraded here — the LR is the aerobic
    # spine; we'd rather move it than gut it. The compliance gate / RPE
    # gate will catch a repeated bad LR via #58 dynamic re-planning.
}


class PlanAdjustmentService:
    """Adjusts the *upcoming* sessions of a plan from daily readiness signals."""

    def __init__(self, plan_repo=None, checkin_repo=None, notification_service=None,
                 adjustment_repo=None):
        self.plan_repo = plan_repo or TrainingPlanRepository()
        self.checkin_repo = checkin_repo or DailyCheckinRepository()
        self.adjustment_repo = adjustment_repo or PlanAdjustmentRepository()
        self._notification_service = notification_service  # lazy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_for_user(self, user_id: int, today: Optional[date] = None) -> dict:
        """Apply readiness-driven adjustments to the user's active plans.

        If today's check-in is missing, falls back to a passive readiness
        signal derived from TSB (``PassiveReadinessService``). The passive
        signal can only trigger the swap rule — the downgrade gate still
        requires real check-ins on both days.

        Returns a summary of what changed (per plan).
        """
        today = today or datetime.now(timezone.utc).date()
        plans = self.plan_repo.get_active_plans(user_id)
        if not plans:
            return {'adjusted': [], 'reason': 'no_active_plans'}

        checkin_today = self.checkin_repo.get_for_date(user_id, today)
        synthetic_used = False
        if checkin_today is None:
            from services.passive_readiness_service import PassiveReadinessService
            checkin_today = PassiveReadinessService().compute_synthetic_checkin(
                user_id, today
            )
            if checkin_today is None:
                return {'adjusted': [], 'reason': 'no_signal'}
            synthetic_used = True

        checkin_yday = self.checkin_repo.get_for_date(user_id, today - timedelta(days=1))
        # Downgrade requires real check-ins on both days. A TSB-driven
        # synthetic is too coarse to safely strip intensity from a quality
        # session — false positives there are expensive to undo.
        two_bad_in_row = bool(
            not synthetic_used
            and checkin_today.is_bad_day
            and checkin_yday
            and checkin_yday.is_bad_day
        )

        summary = []
        for plan in plans:
            result = self._adjust_plan(
                plan, user_id, today, checkin_today, two_bad_in_row, synthetic_used
            )
            if result:
                summary.append(result)

        if summary:
            self.plan_repo.commit()
        return {'adjusted': summary}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _adjust_plan(self, plan, user_id: int, today: date, checkin_today,
                     two_bad_in_row: bool, synthetic_used: bool = False):
        weeks = copy.deepcopy(plan.weeks or [])
        if not weeks:
            return None

        # Locate today's day within the plan's week JSON. Weeks may carry
        # explicit start_date; fall back to plan_start + week index.
        plan_start = self._plan_start(plan)
        week, today_day = self._find_day(weeks, today, plan_start)
        if not week or not today_day:
            return None

        changed_fields = []

        # Rule 1: bad readiness + quality today → swap with easiest later day.
        if checkin_today.is_bad_day and today_day.get('workout_type') in QUALITY_TYPES:
            swap = self._swap_today_with_easy(week, today, today_day, plan_start, user_id)
            if swap:
                changed_fields.append(swap)

        # Rule 2: two bad days in a row → downgrade the next quality session
        # (within 3 days) so we don't pile a third stressor.
        if two_bad_in_row:
            downgrade = self._downgrade_next_quality(weeks, today, plan_start, horizon_days=3)
            if downgrade:
                changed_fields.append(downgrade)

        if not changed_fields:
            return None

        plan.weeks = weeks
        self._record(plan, user_id, changed_fields, checkin_today, synthetic_used)
        self._notify(user_id, plan, changed_fields, synthetic_used)
        return {
            'plan_id': plan.id,
            'plan_name': plan.plan_name,
            'changes': changed_fields,
            'source': 'synthetic' if synthetic_used else 'manual',
        }

    def _swap_today_with_easy(self, week: dict, today: date, today_day: dict, plan_start: date, user_id: int):
        """Find the easiest remaining day this week and swap workouts.

        "Easiest" = ``recovery`` > ``easy_strides`` > ``easy_pickups`` > ``easy``
        > anything else. Days in the past, today itself, rest days, and the
        long-run / race-simulation day are not candidates.
        """
        days = week.get('days') or []
        easiest_idx = None
        easiest_rank = -1
        for i, d in enumerate(days):
            d_date = self._day_calendar_date(week, d, plan_start)
            if not d_date or d_date <= today:
                continue
            wt = d.get('workout_type')
            if wt not in EASY_SWAP_TYPES:
                continue
            rank = self._easy_rank(wt)
            if rank > easiest_rank:
                easiest_rank = rank
                easiest_idx = i

        if easiest_idx is None:
            return None

        target = days[easiest_idx]
        swap = self._swap_day_payloads(today_day, target)
        # Route travels with the workout; only a weekday owned by another location re-matches.
        from services.route_matcher import rematch_stale_days
        rematch_stale_days(user_id, [today_day, target])
        return swap

    @staticmethod
    def _easy_rank(workout_type: str) -> int:
        order = ('easy', 'easy_pickups', 'easy_strides', 'recovery')
        try:
            return order.index(workout_type)
        except ValueError:
            return -1

    @staticmethod
    def _swap_day_payloads(today_day: dict, target_day: dict) -> dict:
        """Swap the workout payload of two days, preserving the ``day`` /
        ``date`` keys (calendar slot stays put — only the workout moves).

        Returns a dict describing what changed (for notifications + audit).
        """
        preserved_keys = {'day', 'date'}
        before = {'today': copy.deepcopy(today_day), 'target': copy.deepcopy(target_day)}
        today_keep = {k: v for k, v in today_day.items() if k in preserved_keys}
        target_keep = {k: v for k, v in target_day.items() if k in preserved_keys}

        today_workout = {k: v for k, v in today_day.items() if k not in preserved_keys}
        target_workout = {k: v for k, v in target_day.items() if k not in preserved_keys}

        today_day.clear()
        today_day.update(today_keep)
        today_day.update(target_workout)

        target_day.clear()
        target_day.update(target_keep)
        target_day.update(today_workout)

        return {
            'kind': 'swap',
            'today_day': today_keep.get('day'),
            'moved_to_day': target_keep.get('day'),
            'workout_type_before': today_workout.get('workout_type'),
            'workout_type_after': today_day.get('workout_type'),
            'payload': {
                'before': before,
                'after': {'today': copy.deepcopy(today_day),
                          'target': copy.deepcopy(target_day)},
            },
        }

    def _downgrade_next_quality(self, weeks: list, today: date, plan_start: date, horizon_days: int):
        """Find the next quality session within ``horizon_days`` and replace
        it with the canonical downgrade (e.g. intervals → easy). Does not
        touch long_run / race_simulation (see DOWNGRADE_MAP)."""
        deadline = today + timedelta(days=horizon_days)
        for week in weeks:
            for day in (week.get('days') or []):
                d_date = self._day_calendar_date(week, day, plan_start)
                if not d_date or d_date <= today or d_date > deadline:
                    continue
                wt = day.get('workout_type')
                if wt not in DOWNGRADE_MAP:
                    continue
                new_type = DOWNGRADE_MAP[wt]
                before = copy.deepcopy(day)
                day['workout_type'] = new_type
                # Strip intensity-specific fields so the new easy day isn't
                # carrying a "tempo" title or a Z4 step list.
                day.pop('steps', None)
                day.pop('intensity', None)
                if day.get('title'):
                    day['title'] = self._easy_title(new_type)
                return {
                    'kind': 'downgrade',
                    'day': day.get('day'),
                    'date': d_date.isoformat(),
                    'workout_type_before': wt,
                    'workout_type_after': new_type,
                    'payload': {'before': before, 'after': copy.deepcopy(day)},
                }
        return None

    @staticmethod
    def _easy_title(workout_type: str) -> str:
        return {
            'easy': 'Easy run (downgraded — readiness low)',
            'recovery': 'Recovery (downgraded — readiness low)',
        }.get(workout_type, 'Easy run')

    @staticmethod
    def _plan_start(plan) -> date:
        created = plan.created_at or datetime.now(timezone.utc)
        created_date = created.date() if isinstance(created, datetime) else created
        return created_date - timedelta(days=created_date.weekday())

    @classmethod
    def _day_calendar_date(cls, week: dict, day_obj: dict, plan_start: date):
        # Prefer explicit ``date`` on the day; fall back to start_date+offset;
        # finally to plan_start + (week_number-1)*7 + day index.
        explicit = day_obj.get('date')
        if explicit:
            try:
                return date.fromisoformat(str(explicit)[:10])
            except (TypeError, ValueError):
                pass
        ws_raw = week.get('start_date')
        ws = None
        if ws_raw:
            try:
                ws = date.fromisoformat(str(ws_raw)[:10])
            except (TypeError, ValueError):
                ws = None
        day_name = day_obj.get('day')
        if day_name not in DAY_NAMES:
            return None
        if ws is None:
            week_num = week.get('week_number') or 1
            ws = plan_start + timedelta(weeks=week_num - 1)
        return ws + timedelta(days=DAY_NAMES.index(day_name))

    def _find_day(self, weeks: list, target: date, plan_start: date):
        for week in weeks:
            for day in (week.get('days') or []):
                d_date = self._day_calendar_date(week, day, plan_start)
                if d_date == target:
                    return week, day
        return None, None

    def _record(self, plan, user_id: int, changes: list, checkin_today,
                synthetic_used: bool = False):
        """Write one structured PlanAdjustment row per applied change.

        Rows are flushed into the same session as the plan mutation, so the
        ``commit()`` in ``apply_for_user`` persists plan + audit atomically.
        Synthetic (TSB-driven) adjustments have no DailyCheckin row, so
        ``checkin_id`` is NULL and the trigger is ``tsb``.
        """
        from models import PlanAdjustment

        trigger = 'tsb' if synthetic_used else 'daily_checkin'
        checkin_id = None if synthetic_used else getattr(checkin_today, 'id', None)

        for change in changes:
            if change['kind'] == 'swap':
                day_before = change.get('today_day')
                day_after = change.get('moved_to_day')
            else:  # downgrade — single day softened in place
                day_before = day_after = change.get('day')
            try:
                self.adjustment_repo.create(PlanAdjustment(
                    plan_id=plan.id,
                    user_id=user_id,
                    kind=change['kind'],
                    trigger=trigger,
                    day_before=day_before,
                    day_after=day_after,
                    workout_type_before=change.get('workout_type_before'),
                    workout_type_after=change.get('workout_type_after'),
                    checkin_id=checkin_id,
                    payload_json=change.get('payload'),
                ))
            except Exception as e:
                logger.warning("Failed to record plan adjustment: %s", e)

    def _notify(self, user_id: int, plan, changes: list, synthetic_used: bool = False):
        try:
            from services.notification_service import NotificationService
            ns = self._notification_service or NotificationService()
        except Exception:
            return

        for change in changes:
            if change['kind'] == 'swap':
                title = "Today's workout was moved"
                if synthetic_used:
                    msg = (
                        f"Recent training load looks fatigued — we swapped today's "
                        f"{change['workout_type_before']} with the easier session on "
                        f"{change['moved_to_day']}. "
                        "Log a daily check-in for more precise tuning."
                    )
                else:
                    msg = (
                        f"Based on your check-in, we swapped today's "
                        f"{change['workout_type_before']} with the easier session "
                        f"scheduled for {change['moved_to_day']}. "
                        "Take an easy day — the quality session is now there."
                    )
            else:
                title = "Quality session softened"
                msg = (
                    f"Two low-readiness days in a row — the {change['workout_type_before']} "
                    f"on {change['day']} was downgraded to {change['workout_type_after']} "
                    "to protect your recovery. Trust the process."
                )
            try:
                ns._create(user_id, 'plan_adjustment', title, msg, plan.id)
            except Exception as e:
                logger.warning("Failed to create plan_adjustment notification: %s", e)

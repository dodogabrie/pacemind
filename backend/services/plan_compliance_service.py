"""Plan compliance service - matches Strava activities to planned workouts."""

import logging
from datetime import datetime, timedelta, timezone
from repositories import TrainingPlanRepository, ActivityRepository, PredictionRepository

logger = logging.getLogger(__name__)

# Map day names to weekday indices (Monday=0)
DAY_TO_INDEX = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6,
}

# Sliding-window matching: when an activity isn't found on the exact target
# date, fall back to ±N days. Long runs and race simulations get a wider
# window because they're the most likely to be shifted by weather / logistics.
DEFAULT_WINDOW_DAYS = 1
WINDOW_BY_TYPE = {
    'long_run': 2,
    'race_simulation': 2,
}


class PlanComplianceService:
    """Matches completed Strava activities against planned workouts."""

    def __init__(self, plan_repo=None, activity_repo=None, prediction_repo=None):
        self.plan_repo = plan_repo or TrainingPlanRepository()
        self.activity_repo = activity_repo or ActivityRepository()
        self.prediction_repo = prediction_repo or PredictionRepository()

    def check_compliance(self, user_id: int, plan_id: int = None) -> dict:
        """Check compliance for user's active plan(s) after Strava sync.

        Args:
            user_id: User ID
            plan_id: Optional specific plan ID. If None, checks all active plans.

        Returns:
            Summary dict with compliance data for one plan, list of summaries
            for multiple plans, or None if no active plan
        """
        if plan_id:
            plan = self.plan_repo.get_user_plan(plan_id, user_id)
            plans = [plan] if plan else []
        else:
            plans = self.plan_repo.get_active_plans(user_id)

        if not plans:
            logger.info(f"No active plan for user {user_id}, skipping compliance check")
            return None

        summaries = []
        for plan in plans:
            summary = self._check_plan_compliance(plan, user_id)
            if summary:
                summaries.append(summary)

        if not summaries:
            return None
        if len(summaries) == 1:
            return summaries[0]
        return summaries

    def _check_plan_compliance(self, plan, user_id: int) -> dict:
        """Check compliance for a single plan."""
        if not plan.weeks:
            return None

        plan_start = self._get_plan_start_date(plan)
        today = datetime.now(timezone.utc).date()

        # Get all activities since plan start
        activities = self.activity_repo.get_user_activities(user_id, after=plan_start)

        # Index activities by date
        activities_by_date = {}
        for activity in activities:
            # Local calendar day, not UTC: a 22:00 run must not count as the
            # next day's workout (see Activity.local_date).
            act_date = activity.local_date
            if act_date not in activities_by_date:
                activities_by_date[act_date] = []
            activities_by_date[act_date].append(activity)

        # Collect every workout that still needs matching. Pre-existing
        # completions already linked to a Strava activity are skipped — once
        # matched, they stay matched.
        pending = []  # list of (week_num, day_name, day_data, target_date, existing)
        for week in plan.weeks:
            week_num = week.get('week_number', 1)
            for day_data in week.get('days', []):
                day_name = day_data.get('day')
                if not day_name or day_name not in DAY_TO_INDEX:
                    continue
                if day_data.get('workout_type') == 'rest':
                    continue
                existing = self.plan_repo.get_completion(plan.id, week_num, day_name)
                if existing and existing.strava_activity_id:
                    continue
                target_date = self._get_workout_date(plan_start, week_num, day_name)
                if target_date is None or target_date > today:
                    continue
                pending.append((week_num, day_name, day_data, target_date, existing))

        # Pass 1 — exact-date match (back-compat with pre-window behaviour).
        # `matched_ids` prevents a single activity from being claimed twice
        # when sliding-window candidates overlap.
        matched_ids = set()
        matches = {}  # (week_num, day_name) -> activity
        for week_num, day_name, day_data, target_date, _existing in pending:
            candidates = [
                a for a in activities_by_date.get(target_date, [])
                if a.id not in matched_ids
            ]
            match = self._find_best_match(candidates, day_data)
            if match:
                matched_ids.add(match.id)
                matches[(week_num, day_name)] = match

        # Pass 2 — sliding window for workouts the user shifted by a day.
        # Iterates in plan order so adjacent workouts with overlapping
        # windows resolve deterministically.
        for week_num, day_name, day_data, target_date, _existing in pending:
            if (week_num, day_name) in matches:
                continue
            window = self._window_for(day_data)
            if window <= 0:
                continue
            match = self._find_best_match_windowed(
                activities_by_date, target_date, day_data, matched_ids, window
            )
            if match:
                matched_ids.add(match.id)
                matches[(week_num, day_name)] = match

        # Persist results.
        completions_created = 0
        for week_num, day_name, day_data, target_date, existing in pending:
            matched_activity = matches.get((week_num, day_name))
            if matched_activity:
                score = self._compute_compliance(day_data, matched_activity)
                status = 'completed' if score >= 80 else 'partial'
                actual_km = matched_activity.distance / 1000 if matched_activity.distance else None
                actual_elev = self._get_elevation_from_streams(matched_activity)
            else:
                score = 0
                status = 'missed'
                actual_km = None
                actual_elev = None

            if existing:
                existing.strava_activity_id = matched_activity.id if matched_activity else None
                existing.actual_distance_km = actual_km
                existing.actual_elevation_m = actual_elev
                existing.compliance_score = score
                existing.status = status
                existing.matched_at = datetime.now(timezone.utc)
            else:
                self.plan_repo.create_completion(
                    user_id=user_id,
                    plan_id=plan.id,
                    week_number=week_num,
                    day=day_name,
                    strava_activity_id=matched_activity.id if matched_activity else None,
                    planned_distance_km=day_data.get('distance_km'),
                    actual_distance_km=actual_km,
                    planned_workout_type=day_data.get('workout_type'),
                    planned_elevation_m=day_data.get('elevation_m'),
                    actual_elevation_m=actual_elev,
                    compliance_score=score,
                    status=status,
                )
                completions_created += 1

        self.plan_repo.commit()
        logger.info(f"Compliance check for plan {plan.id}, user {user_id}: created/updated {completions_created} completions")

        # Track prediction trend if target GPX exists
        self._track_prediction_trend(plan, user_id)

        # Generate notifications
        self._generate_notifications(plan, user_id)

        return self.get_compliance_summary(plan.id, user_id)

    def get_compliance_summary(self, plan_id: int, user_id: int) -> dict:
        """Build compliance summary for a plan.

        Args:
            plan_id: Training plan ID
            user_id: User ID (for auth check)

        Returns:
            Dict with week-by-week compliance data
        """
        plan = self.plan_repo.get_user_plan(plan_id, user_id)
        if not plan:
            return None

        completions = self.plan_repo.get_completions_for_plan(plan_id)
        completions_map = {}
        for c in completions:
            completions_map[(c.week_number, c.day)] = c

        plan_start = self._get_plan_start_date(plan)
        today = datetime.now(timezone.utc).date()
        current_week = max(1, (today - plan_start).days // 7 + 1)
        total_weeks = len(plan.weeks) if plan.weeks else 0

        weeks_data = []
        total_score = 0
        total_scored = 0

        for week in (plan.weeks or []):
            week_num = week.get('week_number', 1)
            days_data = []

            for day_info in week.get('days', []):
                day_name = day_info.get('day')
                completion = completions_map.get((week_num, day_name))
                target_date = self._get_workout_date(plan_start, week_num, day_name)

                if day_info.get('workout_type') == 'rest':
                    day_status = 'rest'
                    day_compliance = None
                elif completion:
                    day_status = completion.status
                    day_compliance = completion.compliance_score
                    if day_compliance is not None:
                        total_score += day_compliance
                        total_scored += 1
                elif target_date and target_date > today:
                    day_status = 'upcoming'
                    day_compliance = None
                else:
                    day_status = 'upcoming'
                    day_compliance = None

                day_entry = {
                    'day': day_name,
                    'status': day_status,
                    'compliance': day_compliance,
                    'planned': {
                        'workout_type': day_info.get('workout_type'),
                        'title': day_info.get('title'),
                        'distance_km': day_info.get('distance_km'),
                        'elevation_m': day_info.get('elevation_m'),
                        'duration_min': day_info.get('duration_min'),
                    },
                    'actual': None,
                }

                if completion and completion.strava_activity_id:
                    day_entry['actual'] = {
                        'distance_km': completion.actual_distance_km,
                        'elevation_m': completion.actual_elevation_m,
                    }

                days_data.append(day_entry)

            week_scores = [d['compliance'] for d in days_data if d['compliance'] is not None]
            week_compliance = round(sum(week_scores) / len(week_scores)) if week_scores else None

            weeks_data.append({
                'week_number': week_num,
                'theme': week.get('theme'),
                'compliance': week_compliance,
                'days': days_data,
            })

        overall = round(total_score / total_scored) if total_scored > 0 else None

        return {
            'plan_id': plan_id,
            'current_week': min(current_week, total_weeks) if total_weeks else 1,
            'total_weeks': total_weeks,
            'overall_compliance': overall,
            'weeks': weeks_data,
        }

    def _get_plan_start_date(self, plan) -> 'date':
        """Get the start date of a plan (Monday of the first week)."""
        created = plan.created_at or datetime.now(timezone.utc)
        created_date = created.date() if isinstance(created, datetime) else created
        # Align to Monday of that week
        days_since_monday = created_date.weekday()
        return created_date - timedelta(days=days_since_monday)

    def _get_workout_date(self, plan_start, week_number: int, day_name: str):
        """Calculate calendar date for a specific workout.

        Args:
            plan_start: Date of plan start (Monday of week 1)
            week_number: 1-indexed week number
            day_name: Day of week ("Monday", "Tuesday", etc.)

        Returns:
            date object, or None if day_name invalid
        """
        day_idx = DAY_TO_INDEX.get(day_name)
        if day_idx is None:
            return None
        return plan_start + timedelta(weeks=week_number - 1, days=day_idx)

    def _find_best_match(self, activities: list, planned_day: dict):
        """Find the best matching activity for a planned workout day.

        If multiple activities on the same day, pick the one closest in distance.
        """
        if not activities:
            return None

        planned_km = planned_day.get('distance_km', 0)
        if not planned_km:
            # If no planned distance, just return the longest activity
            return max(activities, key=lambda a: a.distance or 0)

        # Pick activity closest to planned distance
        def distance_diff(act):
            act_km = (act.distance or 0) / 1000
            return abs(act_km - planned_km)

        return min(activities, key=distance_diff)

    def _window_for(self, day_data: dict) -> int:
        """Days of slack allowed when matching a planned workout to an activity."""
        return WINDOW_BY_TYPE.get(day_data.get('workout_type'), DEFAULT_WINDOW_DAYS)

    def _find_best_match_windowed(self, activities_by_date, target_date,
                                  day_data, exclude_ids, window):
        """Find the best match in ``target_date ± window`` days, skipping
        activities already claimed in an earlier pass.

        Scoring (lexicographic, highest wins):
          1. workout-type match (closer-in-kind preferred over closer-in-time)
          2. -abs(days_offset) — temporally closer wins
          3. -abs(distance_diff_km) — distance-closer breaks remaining ties
        """
        planned_type = day_data.get('workout_type')
        planned_km = day_data.get('distance_km') or 0

        best = None
        best_score = None
        for offset in range(-window, window + 1):
            if offset == 0:
                continue  # exact-date already handled in Pass 1
            scan_date = target_date + timedelta(days=offset)
            for act in activities_by_date.get(scan_date, []):
                if act.id in exclude_ids:
                    continue
                type_match = 1 if (
                    planned_type and self._infer_workout_type(act) == planned_type
                ) else 0
                act_km = (act.distance or 0) / 1000
                dist_diff = abs(act_km - planned_km) if planned_km else 0
                score = (type_match, -abs(offset), -dist_diff)
                if best_score is None or score > best_score:
                    best_score = score
                    best = act
        return best

    def _generate_notifications(self, plan, user_id: int):
        """Generate notifications based on compliance and race countdown."""
        try:
            from services.notification_service import NotificationService
            ns = NotificationService()

            # Weekly summary — check if it's Sunday or if compliance was just computed
            summary = self.get_compliance_summary(plan.id, user_id)
            if summary:
                overall = summary.get('overall_compliance')
                if overall is not None:
                    # Generate weekly summary
                    ns.generate_weekly_summary(user_id, plan.id, overall)
                    # Coach suggestion if low compliance
                    if overall < 60:
                        ns.generate_coach_suggestion(user_id, plan.id)

            # Race countdown notifications
            if plan.race_date:
                today = datetime.now(timezone.utc).date()
                race_date = plan.race_date.date() if isinstance(plan.race_date, datetime) else plan.race_date
                days_to_race = (race_date - today).days
                if days_to_race in (7, 3, 1):
                    ns.generate_race_countdown(user_id, plan.id, days_to_race)
        except Exception as e:
            logger.warning(f"Failed to generate notifications: {e}")

    def _infer_workout_type(self, activity) -> str:
        """Infer workout type from Strava activity data.

        Uses pace, distance, duration, and elevation patterns:
        - easy: avg pace > 80% of typical, low effort
        - tempo: sustained moderate-hard pace
        - intervals: high pace variance
        - long_run: distance > 15km or duration > 90min
        - hill_repeats: repeated elevation gain/loss cycles
        - recovery: very short/slow run
        """
        actual_km = (activity.distance or 0) / 1000
        # moving_time / elapsed_time / average_speed / max_speed are not
        # columns on the local Activity model — guard with getattr so
        # this stays robust when the activity is loaded without those fields.
        moving_time = getattr(activity, 'moving_time', None)
        elapsed_time = getattr(activity, 'elapsed_time', None)
        duration_min = ((moving_time or elapsed_time) or 0) / 60

        if actual_km < 0.5 or duration_min < 5:
            return 'rest'

        # Long run: distance > 15km or duration > 90min
        if actual_km > 15 or duration_min > 90:
            return 'long_run'

        # Recovery: very short
        if actual_km < 5 and duration_min < 30:
            return 'recovery'

        # Check elevation for hill repeats: high elevation gain relative to distance
        elev = self._get_elevation_from_streams(activity)
        if elev and actual_km > 0 and (elev / actual_km) > 50:
            return 'hill_repeats'

        # Check pace variance using average speed
        avg_speed = getattr(activity, 'average_speed', None) or None
        max_speed = getattr(activity, 'max_speed', None) or None

        if avg_speed and max_speed and avg_speed > 0:
            speed_ratio = max_speed / avg_speed
            # High speed variation suggests intervals
            if speed_ratio > 1.8:
                return 'intervals'
            # Moderate-fast sustained pace suggests tempo
            if speed_ratio < 1.4 and duration_min > 20:
                pace_min_km = (1000 / avg_speed) / 60 if avg_speed > 0 else 999
                if pace_min_km < 6.0:
                    return 'tempo'

        return 'easy'

    # Daily readiness check-in + same-week swap/downgrade is implemented in
    # services.plan_adjustment_service.PlanAdjustmentService (coach-review #55).
    # Compliance scoring (this service) stays post-hoc and unchanged.
    # TODO(coach-review #58 — see GH issues): no dynamic re-planning from compliance.
    # If 2-week rolling compliance < 70% or TSB < -15, the engine should regenerate
    # the remaining weeks (reduced volume, push peak by 1w). Today we only emit a
    # notification — the plan stays unchanged.
    def _compute_compliance(self, planned_day: dict, activity) -> int:
        """Compute compliance score 0-100 between planned and actual.

        Weighted: 60% distance match, 20% elevation match, 20% workout type match.
        """
        score = 0
        weights_used = 0

        # Distance compliance (60%)
        planned_km = planned_day.get('distance_km')
        actual_km = (activity.distance or 0) / 1000

        if planned_km and planned_km > 0:
            ratio = actual_km / planned_km
            if 0.8 <= ratio <= 1.2:
                dist_score = 100
            elif ratio < 0.8:
                dist_score = max(0, ratio / 0.8 * 100)
            else:
                dist_score = max(0, 100 - (ratio - 1.2) * 200)
            score += dist_score * 0.6
            weights_used += 0.6

        # Elevation compliance (20%)
        planned_elev = planned_day.get('elevation_m')
        actual_elev = self._get_elevation_from_streams(activity)

        if planned_elev and planned_elev > 0 and actual_elev is not None:
            ratio = actual_elev / planned_elev
            if 0.7 <= ratio <= 1.3:
                elev_score = 100
            elif ratio < 0.7:
                elev_score = max(0, ratio / 0.7 * 100)
            else:
                elev_score = max(0, 100 - (ratio - 1.3) * 200)
            score += elev_score * 0.2
            weights_used += 0.2

        # Workout type compliance (20%)
        planned_type = planned_day.get('workout_type')
        if planned_type and planned_type not in ('rest', 'cross_train'):
            inferred_type = self._infer_workout_type(activity)
            if inferred_type == planned_type:
                type_score = 100
            elif {inferred_type, planned_type} & {'easy', 'recovery'}:
                # Easy and recovery are close enough
                type_score = 70
            else:
                type_score = 30
            score += type_score * 0.2
            weights_used += 0.2

        if weights_used > 0:
            return round(score / weights_used)

        # If no planned metrics to compare, count as completed
        return 100

    def _track_prediction_trend(self, plan, user_id: int):
        """If plan has a target_gpx_id, run a prediction and append to history."""
        if not plan.target_gpx_id:
            return

        today_str = datetime.now(timezone.utc).date().isoformat()
        history = plan.prediction_history or []

        # Only track once per day
        if history and history[-1].get('date') == today_str:
            return

        try:
            latest_pred = self.prediction_repo.get_latest_for_gpx(plan.target_gpx_id, user_id)
            if latest_pred and hasattr(latest_pred, 'total_time_seconds') and latest_pred.total_time_seconds:
                history.append({
                    'date': today_str,
                    'predicted_seconds': latest_pred.total_time_seconds,
                })
                plan.prediction_history = history
                self.plan_repo.commit()
                logger.info(f"Tracked prediction trend for plan {plan.id}: {latest_pred.total_time_seconds}s")
        except Exception as e:
            logger.warning(f"Failed to track prediction trend: {e}")

    def _get_elevation_from_streams(self, activity) -> float:
        """Extract total elevation gain from activity streams."""
        streams = activity.streams
        if not streams or not isinstance(streams, dict):
            return None

        altitude = streams.get('altitude')
        if not altitude or not isinstance(altitude, list) or len(altitude) < 2:
            return None

        gain = 0
        for i in range(1, len(altitude)):
            diff = altitude[i] - altitude[i - 1]
            if diff > 0:
                gain += diff

        return round(gain, 1)

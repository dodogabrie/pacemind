"""Adaptive Strava-history inference of the user's training time budget.

Used by the onboarding wizard to pre-fill hours-based fields. The lookback
window expands until we have enough samples for a confident estimate, or we
hit the 52-week cap.

Confidence levels:
    high   -> >= 30 activities AND >= 8 active weeks within the window
    medium -> >= 12 activities AND >= 4 active weeks
    low    -> below those thresholds (returns conservative defaults)
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


WINDOW_STEPS = (12, 16, 24, 36, 52)
HIGH_MIN_ACTIVITIES = 30
HIGH_MIN_WEEKS = 8
MEDIUM_MIN_ACTIVITIES = 12
MEDIUM_MIN_WEEKS = 4

MOUNTAIN_ELEV_THRESHOLD_M = 300.0  # activity counts as "mountain" if D+ >= this

# Conservative defaults when we don't have enough Strava history.
LOW_CONFIDENCE_DEFAULTS = {
    'available_hours_per_week': 4.0,
    'usual_midweek_hours': 1.0,
    'max_long_run_hours': 2.0,
    'long_run_day_inferred': 'Saturday',
    'mountain_runs_per_week': 0.0,
    'mountain_days_inferred': [],
    'usual_mountain_hours': 0.0,
}


def _activity_duration_hours(activity) -> Optional[float]:
    """Pull elapsed/moving time in hours from an activity. Falls back to streams['time']."""
    streams = getattr(activity, 'streams', None) or getattr(activity, '_streams', None)
    if isinstance(streams, dict):
        time_stream = streams.get('time')
        if isinstance(time_stream, list) and time_stream:
            try:
                last = float(time_stream[-1])
                if last > 0:
                    return last / 3600.0
            except (TypeError, ValueError):
                pass
    # Some imports may carry moving_time / elapsed_time directly even though
    # they aren't declared on the model — defensive getattr.
    for attr in ('moving_time', 'elapsed_time'):
        v = getattr(activity, attr, None)
        if v is not None:
            try:
                return float(v) / 3600.0
            except (TypeError, ValueError):
                continue
    return None


def _activity_elevation_m(activity) -> float:
    """Total D+ in metres (best-effort across schemas)."""
    for attr in ('total_elevation_gain', 'elevation_gain', 'elev_gain_m'):
        v = getattr(activity, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    streams = getattr(activity, 'streams', None) or getattr(activity, '_streams', None)
    if isinstance(streams, dict):
        alt = streams.get('altitude') or streams.get('elevation')
        if isinstance(alt, list) and len(alt) >= 2:
            gain = 0.0
            for a, b in zip(alt[:-1], alt[1:]):
                try:
                    delta = float(b) - float(a)
                    if delta > 0:
                        gain += delta
                except (TypeError, ValueError):
                    continue
            return gain
    return 0.0


def _classify_confidence(n_activities: int, n_weeks: int) -> str:
    if n_activities >= HIGH_MIN_ACTIVITIES and n_weeks >= HIGH_MIN_WEEKS:
        return 'high'
    if n_activities >= MEDIUM_MIN_ACTIVITIES and n_weeks >= MEDIUM_MIN_WEEKS:
        return 'medium'
    return 'low'


def _weekday_name(dt: datetime) -> str:
    return ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
            'Friday', 'Saturday', 'Sunday'][dt.weekday()]


def _infer_from_activities(activities: list, lookback_weeks: int) -> dict:
    """Compute capacity stats from the activity sample (used inside the loop)."""
    if not activities:
        return {
            'sample_size_activities': 0,
            'sample_size_weeks': 0,
            'lookback_weeks_used': lookback_weeks,
            'confidence': 'low',
            'fallback_used': True,
            **LOW_CONFIDENCE_DEFAULTS,
        }

    # Bucket activities per ISO week (YYYY-WW).
    weekly_hours: dict[str, float] = {}
    midweek_durations: list[float] = []
    long_run_durations: list[float] = []
    long_run_weekdays: list[str] = []
    mountain_durations: list[float] = []
    mountain_weekdays: list[str] = []
    mountain_per_week: dict[str, int] = {}

    for act in activities:
        dur_h = _activity_duration_hours(act)
        if dur_h is None or dur_h <= 0:
            continue
        start = getattr(act, 'start_date', None)
        if not isinstance(start, datetime):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        iso_year, iso_week, iso_weekday = start.isocalendar()
        wkey = f'{iso_year}-{iso_week:02d}'
        weekly_hours[wkey] = weekly_hours.get(wkey, 0.0) + dur_h

        weekday_name = _weekday_name(start)
        # Midweek = Mon-Fri runs.
        if iso_weekday <= 5:
            midweek_durations.append(dur_h)

        # Heuristic: longest single activity in each week is the "long run".
        # We collect candidates, deduplicate later by week.
        long_run_durations.append(dur_h)
        long_run_weekdays.append(weekday_name)

        elev = _activity_elevation_m(act)
        if elev >= MOUNTAIN_ELEV_THRESHOLD_M:
            mountain_durations.append(dur_h)
            mountain_weekdays.append(weekday_name)
            mountain_per_week[wkey] = mountain_per_week.get(wkey, 0) + 1

    n_activities = sum(
        1 for a in activities if _activity_duration_hours(a) is not None
    )
    n_weeks = len(weekly_hours)
    confidence = _classify_confidence(n_activities, n_weeks)

    if confidence == 'low' or not weekly_hours:
        return {
            'sample_size_activities': n_activities,
            'sample_size_weeks': n_weeks,
            'lookback_weeks_used': lookback_weeks,
            'confidence': 'low',
            'fallback_used': True,
            **LOW_CONFIDENCE_DEFAULTS,
        }

    available = statistics.median(weekly_hours.values())
    midweek = statistics.median(midweek_durations) if midweek_durations else 1.0
    longest = max(long_run_durations) if long_run_durations else 2.0
    # Long-run day: most common weekday for activities at >= 75% of the longest.
    threshold = longest * 0.75
    candidate_days = [
        long_run_weekdays[i] for i, d in enumerate(long_run_durations)
        if d >= threshold
    ]
    long_run_day = (
        statistics.mode(candidate_days)
        if candidate_days else 'Saturday'
    )

    mountain_per_week_avg = (
        sum(mountain_per_week.values()) / max(n_weeks, 1) if mountain_per_week else 0.0
    )
    mountain_days_inferred = sorted(set(mountain_weekdays))
    usual_mountain_hours = (
        statistics.median(mountain_durations) if mountain_durations else 0.0
    )

    return {
        'available_hours_per_week': round(available, 2),
        'usual_midweek_hours': round(midweek, 2),
        'max_long_run_hours': round(longest, 2),
        'long_run_day_inferred': long_run_day,
        'mountain_runs_per_week': round(mountain_per_week_avg, 2),
        'mountain_days_inferred': mountain_days_inferred,
        'usual_mountain_hours': round(usual_mountain_hours, 2),
        'lookback_weeks_used': lookback_weeks,
        'sample_size_weeks': n_weeks,
        'sample_size_activities': n_activities,
        'confidence': confidence,
        'fallback_used': False,
    }


def infer_capacity(user_id: int, *, _activity_loader=None) -> dict:
    """Infer the user's training time budget from Strava history.

    Adaptive lookback: starts at 12 weeks and expands up to 52 until we hit
    HIGH thresholds, then stops. Returns conservative defaults at low
    confidence so the wizard can still pre-fill something.

    `_activity_loader` is injected by tests to avoid hitting the DB; it
    receives (user_id, since_dt) and must return a list of Activity-like
    objects.
    """
    loader = _activity_loader or _default_loader
    now = datetime.now(timezone.utc)

    last_result: dict = {}
    for window in WINDOW_STEPS:
        since = now - timedelta(weeks=window)
        activities = loader(user_id, since)
        last_result = _infer_from_activities(activities, window)
        if last_result.get('confidence') == 'high':
            break
    return last_result


def _default_loader(user_id: int, since_dt: datetime) -> list:
    """Production loader — pulls Activity rows for a user since `since_dt`."""
    try:
        from models import Activity
        from database import db
        return (
            db.session.query(Activity)
            .filter(Activity.user_id == user_id)
            .filter(Activity.start_date >= since_dt)
            .all()
        )
    except Exception:
        # No flask context / no DB — fall back to empty.
        return []

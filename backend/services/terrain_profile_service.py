"""Infer the user's typical training terrain profile from Strava history.

Output is consumed by:
  - the onboarding wizard (step 3 default selection)
  - the plan engine (MIDWEEK_ELEV_CAP lookup)
  - validate_plan_feasibility (race_terrain_mismatch)
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional


_DEFAULT_LOOKBACK_DAYS = 90


def _activity_elev_gain(activity) -> Optional[float]:
    streams = getattr(activity, 'streams', None)
    if not streams or not isinstance(streams, dict):
        return None
    altitude = streams.get('altitude')
    if not altitude or not isinstance(altitude, list) or len(altitude) < 2:
        return None
    gain = 0.0
    for i in range(1, len(altitude)):
        diff = altitude[i] - altitude[i - 1]
        if diff > 0:
            gain += diff
    return gain


def _classify(median: float, p90: float) -> str:
    if median <= 10 and p90 <= 25:
        return 'flat_urban'
    if median <= 30:
        return 'rolling_hills'
    return 'mountain'


def _confidence(sample_count: int) -> str:
    if sample_count < 5:
        return 'low'
    if sample_count < 15:
        return 'medium'
    return 'high'


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def infer_user_terrain_profile(
    user_id: int,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> dict:
    """Compute terrain stats from the user's recent Strava activities.

    Returns:
      {
        'profile': 'flat_urban' | 'rolling_hills' | 'mountain' | None,
        'median_elev_density': float,
        'p90_elev_density': float,
        'max_single_run_elev': int,
        'sample_count': int,
        'confidence': 'low' | 'medium' | 'high',
        'training_base': {'lat', 'lon'} | None,
      }
    """
    # Imports kept local — keeps the module testable without a Flask app context
    # for callers that pass pre-computed activity stats.
    from repositories import ActivityRepository
    from services.route_generation_service import RouteGenerationService

    repo = ActivityRepository()
    after = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    try:
        activities = repo.get_user_activities(user_id, after=after)
    except Exception:
        activities = []

    densities: list[float] = []
    max_elev = 0.0
    for act in activities:
        distance_m = getattr(act, 'distance', 0) or 0
        if distance_m <= 0:
            continue
        gain = _activity_elev_gain(act)
        if gain is None:
            continue
        distance_km = distance_m / 1000.0
        if distance_km < 1.0:  # ignore micro-activities
            continue
        density = gain / distance_km
        densities.append(density)
        if gain > max_elev:
            max_elev = gain

    sample_count = len(densities)
    if sample_count == 0:
        return {
            'profile': None,
            'median_elev_density': 0.0,
            'p90_elev_density': 0.0,
            'max_single_run_elev': 0,
            'sample_count': 0,
            'confidence': 'low',
            'training_base': None,
        }

    median = float(statistics.median(densities))
    p90 = float(_percentile(densities, 0.9))

    try:
        base = RouteGenerationService().infer_training_base(user_id)
    except Exception:
        base = None

    return {
        'profile': _classify(median, p90),
        'median_elev_density': round(median, 2),
        'p90_elev_density': round(p90, 2),
        'max_single_run_elev': int(round(max_elev)),
        'sample_count': sample_count,
        'confidence': _confidence(sample_count),
        'training_base': (
            {'lat': base['lat'], 'lon': base['lon']}
            if base and 'lat' in base and 'lon' in base
            else None
        ),
    }


def persist_inferred_profile(user_id: int, inferred: dict) -> None:
    """Save an inferred profile to UserTrainingPreferences IFF source != 'user'.

    Never overwrites an explicit user choice.
    """
    profile = inferred.get('profile')
    if not profile:
        return
    from repositories import UserTrainingPreferencesRepository

    repo = UserTrainingPreferencesRepository()
    prefs = repo.get_by_user(user_id)
    if prefs and (prefs.terrain_profile_source or 'inferred') == 'user':
        return
    repo.upsert(user_id, {
        'terrain_profile': profile,
        'terrain_profile_source': 'inferred',
    })

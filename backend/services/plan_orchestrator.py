"""Thin orchestrator: prefs → engine → route matcher → feasibility validation.

Keeps ``plan_engine`` decoupled from repositories. The agent tool handler
calls the orchestrator instead of the engine directly so prefs/route binding
happen consistently.
"""

from __future__ import annotations

from typing import Optional

from services import plan_engine
from services.plan_engine import MissingPreferencesError, REQUIRED_PREFS_FIELDS


def _missing_required(prefs: dict | None) -> list[str]:
    if not prefs:
        return list(REQUIRED_PREFS_FIELDS)
    return [f for f in REQUIRED_PREFS_FIELDS if prefs.get(f) in (None, '', [])]


def _wrap_weeks_as_plan_obj(user_id: int, weeks: list[dict]):
    """Lightweight stand-in for a TrainingPlan ORM instance."""
    class _PlanProxy:
        pass
    p = _PlanProxy()
    p.user_id = user_id
    p.weeks = weeks
    return p


def generate_plan_with_routes(
    user_id: int,
    *,
    total_weeks: int,
    race_distance_km: float,
    race_elevation_m: float,
    race_date: str,
    athlete_weekly_km: float,
    athlete_weekly_elev: float,
    athlete_longest_run_km: float,
    athlete_category: str,
    long_run_day: str,
    rest_days: list[str],
    race_type: str = 'loop',
    training_ratio: Optional[float] = None,
    key_sections: list[dict] | None = None,
    back_to_back: bool = False,
    overrides: dict | None = None,
    strength_days: int = 0,
    strength_preferred_days: list[str] | None = None,
    athlete_flat_pace_min_km: Optional[float] = None,
    prefs: dict | None = None,
    bind_routes: bool = True,
) -> dict:
    """Generate a plan and bind real routes/feasibility warnings.

    Raises:
        MissingPreferencesError: when required prefs (max_weekly_km, terrain_profile)
            are absent. Caller (the agent tool handler) catches this and surfaces
            the onboarding wizard to the user.

    Returns:
      {
        'weeks': [...],
        'route_match_summary': {matched, approx, unmatched, unmatched_workouts},
        'warnings': [...feasibility warnings...],
      }
    """
    missing = _missing_required(prefs)
    if missing:
        raise MissingPreferencesError(missing)

    terrain_profile = prefs.get('terrain_profile') if prefs else None
    mountain_days = (prefs.get('mountain_days') if prefs else None) or None

    weeks = plan_engine.generate_plan(
        total_weeks=total_weeks,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_date=race_date,
        athlete_weekly_km=athlete_weekly_km,
        athlete_weekly_elev=athlete_weekly_elev,
        athlete_longest_run_km=athlete_longest_run_km,
        athlete_category=athlete_category,
        long_run_day=long_run_day,
        rest_days=rest_days,
        race_type=race_type,
        training_ratio=training_ratio,
        key_sections=key_sections,
        back_to_back=back_to_back,
        overrides=overrides,
        mountain_days=mountain_days,
        strength_days=strength_days,
        strength_preferred_days=strength_preferred_days,
        prefs=prefs,
        terrain_profile=terrain_profile,
        athlete_flat_pace_min_km=athlete_flat_pace_min_km,
    )

    route_summary = {'matched': 0, 'approx': 0, 'unmatched': 0, 'unmatched_workouts': []}
    if bind_routes:
        try:
            from services.route_matcher import match_routes_to_plan
            proxy = _wrap_weeks_as_plan_obj(user_id, weeks)
            route_summary = match_routes_to_plan(proxy, prefs)
            weeks = proxy.weeks
        except Exception:
            # Route binding is best-effort: the plan stays valid even if
            # the matcher errors (eg. DB connectivity hiccup in tests).
            pass

    warnings = plan_engine.validate_plan_feasibility(
        weeks,
        prefs,
        terrain_profile,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
    )

    return {
        'weeks': weeks,
        'route_match_summary': route_summary,
        'warnings': warnings,
    }

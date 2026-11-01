"""Time-budget warnings: weekly_hours_above_cap and long_run_hours_above_cap."""
from services.plan_engine import generate_plan, validate_plan_feasibility


def _build_plan(prefs):
    return generate_plan(
        total_weeks=10,
        race_distance_km=42,
        race_elevation_m=1500,
        race_date='2026-08-01',
        athlete_weekly_km=50,
        athlete_weekly_elev=1200,
        athlete_longest_run_km=25,
        athlete_category='cat_2',
        long_run_day='Saturday',
        rest_days=['Monday'],
        prefs=prefs,
    )


def test_weekly_hours_above_cap_fires_when_budget_too_low():
    """A 50 km/week plan against a 2 h/week budget must trip the warning."""
    prefs = {
        'max_weekly_km': 80,
        'terrain_profile': 'rolling_hills',
        'available_hours_per_week': 2.0,  # absurdly low
    }
    weeks = _build_plan(prefs)
    warnings = validate_plan_feasibility(
        weeks, prefs=prefs, terrain_profile='rolling_hills',
        race_distance_km=42, race_elevation_m=1500,
    )
    codes = [w.get('code') for w in warnings]
    assert 'weekly_hours_above_cap' in codes


def test_weekly_hours_above_cap_silent_when_budget_generous():
    prefs = {
        'max_weekly_km': 80,
        'terrain_profile': 'rolling_hills',
        'available_hours_per_week': 20.0,  # generous — should never fire
    }
    weeks = _build_plan(prefs)
    warnings = validate_plan_feasibility(
        weeks, prefs=prefs, terrain_profile='rolling_hills',
        race_distance_km=42, race_elevation_m=1500,
    )
    codes = [w.get('code') for w in warnings]
    assert 'weekly_hours_above_cap' not in codes


def test_long_run_hours_above_cap_fires_when_too_short():
    """Forbid a 25-km long run capacity into a 30-min budget."""
    prefs = {
        'max_weekly_km': 80,
        'terrain_profile': 'rolling_hills',
        'max_long_run_hours': 0.5,  # 30 minutes — way too short
    }
    # The engine now sizes the long run to the cap (#115), so validate a plan
    # built without it against the tight cap.
    weeks = _build_plan({k: v for k, v in prefs.items() if k != 'max_long_run_hours'})
    warnings = validate_plan_feasibility(
        weeks, prefs=prefs, terrain_profile='rolling_hills',
        race_distance_km=42, race_elevation_m=1500,
    )
    codes = [w.get('code') for w in warnings]
    assert 'long_run_hours_above_cap' in codes


def test_long_run_hours_above_cap_silent_when_generous():
    prefs = {
        'max_weekly_km': 80,
        'terrain_profile': 'rolling_hills',
        'max_long_run_hours': 6.0,
    }
    weeks = _build_plan(prefs)
    warnings = validate_plan_feasibility(
        weeks, prefs=prefs, terrain_profile='rolling_hills',
        race_distance_km=42, race_elevation_m=1500,
    )
    codes = [w.get('code') for w in warnings]
    assert 'long_run_hours_above_cap' not in codes


def test_no_hours_pref_means_no_hours_warnings():
    """If the user hasn't set any hours field, the new warnings stay silent."""
    prefs = {'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'}
    weeks = _build_plan(prefs)
    warnings = validate_plan_feasibility(
        weeks, prefs=prefs, terrain_profile='rolling_hills',
        race_distance_km=42, race_elevation_m=1500,
    )
    codes = [w.get('code') for w in warnings]
    assert 'weekly_hours_above_cap' not in codes
    assert 'long_run_hours_above_cap' not in codes

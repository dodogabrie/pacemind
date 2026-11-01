"""User capacity caps applied by compute_weekly_targets / generate_plan."""

from services import plan_engine


def _gen(prefs, *, total_weeks=8, race_distance_km=30, race_elevation_m=900,
         athlete_weekly_km=70, athlete_longest_run_km=25,
         athlete_flat_pace_min_km=None):
    return plan_engine.generate_plan(
        total_weeks=total_weeks,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_date='2026-08-30',
        athlete_weekly_km=athlete_weekly_km,
        athlete_weekly_elev=1500,
        athlete_longest_run_km=athlete_longest_run_km,
        athlete_category='cat_2',
        long_run_day='Sunday',
        rest_days=['Friday'],
        prefs=prefs,
        athlete_flat_pace_min_km=athlete_flat_pace_min_km,
    )


def test_max_weekly_km_clamps_targets_with_prefs():
    prefs = {
        'max_weekly_km': 40,
        'max_long_run_km': 22,
        'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
    }
    weeks = _gen(prefs, total_weeks=10, athlete_weekly_km=70)
    # The engine clamps the *target* used to size each day. Because distribute_week
    # uses workout-type minimums, total_km may slightly exceed the target — but the
    # peak run-time cap is clearly enforced (weekly target stays around 40, not 90+).
    # Race week is intentionally exempt: total_km includes the race itself
    # (event-day load, not training load), so a 30 km race with a 40 km cap
    # legitimately ships ~60 km (race + RACE_WEEK_EXTRA_KM pre-race volume).
    for w in weeks:
        if (w.get('theme') or '').startswith('Race'):
            continue
        assert w['total_km'] <= 55, f"week {w['week_number']} total_km={w['total_km']}"


def test_max_long_run_km_caps_long_runs():
    prefs = {
        'max_weekly_km': 60,
        'max_long_run_km': 18,
        'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
    }
    weeks = _gen(prefs, total_weeks=8, race_distance_km=42, athlete_longest_run_km=30)
    long_runs = [d['distance_km']
                 for w in weeks for d in w['days']
                 if d['workout_type'] == 'long_run']
    assert long_runs, "expected at least one long_run"
    assert max(long_runs) <= 18 + 0.05  # tolerance for rounding


def test_max_long_run_hours_with_flat_pace_caps_long_run():
    prefs = {
        'max_weekly_km': 80,
        'max_long_run_hours': 2.0,  # 2h * 60min / 6min per km = 20km
        'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
    }
    weeks = _gen(prefs, total_weeks=8, race_distance_km=42,
                 athlete_longest_run_km=30, athlete_flat_pace_min_km=6.0)
    long_runs = [d['distance_km'] for w in weeks for d in w['days']
                 if d['workout_type'] == 'long_run']
    assert max(long_runs) <= 20 + 0.05


def test_no_prefs_back_compat():
    """prefs=None preserves the legacy behaviour (no caps)."""
    weeks = _gen(None, total_weeks=6, athlete_weekly_km=50)
    # Some week somewhere should exceed 40km — proves no cap is silently applied.
    assert any(w['total_km'] > 40 for w in weeks)


def test_lr_multiplier_compatible_with_cap():
    """When max_weekly_km < WEEKLY_MIN_LR_MULTIPLIER * long_run_km, engine shrinks long_run."""
    prefs = {
        'max_weekly_km': 30,
        'max_long_run_km': 25,  # nominally 25, but 25*1.6 = 40 > weekly cap of 30
        'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'flat_urban',
    }
    weeks = _gen(prefs, total_weeks=4, race_distance_km=20, athlete_longest_run_km=20)
    # Expected: long run forced down to ~30/1.6 = 18.75
    long_runs = [d['distance_km'] for w in weeks for d in w['days']
                 if d['workout_type'] == 'long_run']
    assert max(long_runs) <= 19 + 0.5

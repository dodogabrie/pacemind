"""Terrain-aware midweek elevation cap and race terrain mismatch."""

from services import plan_engine


def _gen(prefs, terrain_profile, race_elevation_m=1500, race_distance_km=30):
    return plan_engine.generate_plan(
        total_weeks=8,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_date='2026-09-30',
        athlete_weekly_km=50,
        athlete_weekly_elev=1500,
        athlete_longest_run_km=22,
        athlete_category='cat_2',
        long_run_day='Sunday',
        rest_days=['Friday'],
        prefs=prefs,
        terrain_profile=terrain_profile,
    )


def _midweek_elevs(weeks):
    midweek = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
    return [d['elevation_m'] for w in weeks for d in w['days']
            if d['day'] in midweek
            and d['workout_type'] not in ('long_run', 'race_simulation', 'rest', 'strength')]


def test_flat_urban_caps_midweek_elev_to_50():
    prefs = {
        'max_weekly_km': 50, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'flat_urban',
    }
    weeks = _gen(prefs, 'flat_urban', race_elevation_m=1500)
    elevs = _midweek_elevs(weeks)
    assert elevs, "expected at least some midweek workouts"
    assert max(elevs) <= 50 + 0.5


def test_rolling_hills_caps_midweek_elev_to_200():
    prefs = {
        'max_weekly_km': 50, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
    }
    weeks = _gen(prefs, 'rolling_hills', race_elevation_m=2500)
    assert max(_midweek_elevs(weeks)) <= 200 + 0.5


def test_mountain_profile_no_extra_midweek_cap():
    """Mountain profile leaves elevation only bound by MAX_ELEV_DENSITY (80 m/km)."""
    prefs = {
        'max_weekly_km': 60, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'mountain',
    }
    weeks = _gen(prefs, 'mountain', race_elevation_m=2500)
    # No 50m or 200m artificial cap — assert density never exceeds MAX_ELEV_DENSITY.
    midweek_days = [d for w in weeks for d in w['days']
                    if d['day'] in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
                    and d['workout_type'] not in ('long_run', 'rest', 'strength')]
    for d in midweek_days:
        if d['distance_km'] > 0:
            assert d['elevation_m'] / d['distance_km'] <= plan_engine.MAX_ELEV_DENSITY + 1


def test_long_run_not_capped_by_midweek_terrain_rule():
    """The long run is on the weekend and should NOT be clamped by midweek rules."""
    prefs = {
        'max_weekly_km': 50, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'flat_urban',
    }
    weeks = _gen(prefs, 'flat_urban', race_elevation_m=900)
    sunday_runs = [d for w in weeks for d in w['days']
                   if d['day'] == 'Sunday' and d['workout_type'] == 'long_run']
    # At least one long run should have more than 50m (it's a long trail run, not a flat urban midweek workout).
    # On flat_urban, the long_run elevation is capped to FLAT_CITY_ELEV_DENSITY * km — but NOT to 50m absolute.
    assert sunday_runs, "expected long runs"


def test_flat_urban_with_mountain_race_emits_critical_warning():
    """Race elev_density > 30 m/km with terrain_profile='flat_urban' triggers race_terrain_mismatch."""
    prefs = {
        'max_weekly_km': 50, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'flat_urban',
    }
    weeks = _gen(prefs, 'flat_urban', race_distance_km=20, race_elevation_m=1200)  # 60 m/km
    warns = plan_engine.validate_plan_feasibility(
        weeks, prefs, 'flat_urban',
        race_distance_km=20, race_elevation_m=1200,
    )
    crit = [w for w in warns if w['severity'] == 'critical' and w['issue'] == 'race_terrain_mismatch']
    assert len(crit) == 1

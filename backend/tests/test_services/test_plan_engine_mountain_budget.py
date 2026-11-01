"""Mountain access budget enforcement (per_week / per_month / fallback)."""

from services import plan_engine


def _gen(prefs, total_weeks=12, race_elevation_m=2500):
    return plan_engine.generate_plan(
        total_weeks=total_weeks,
        race_distance_km=42,
        race_elevation_m=race_elevation_m,
        race_date='2026-10-30',
        athlete_weekly_km=60,
        athlete_weekly_elev=2000,
        athlete_longest_run_km=28,
        athlete_category='cat_2',
        long_run_day='Sunday',
        rest_days=['Friday'],
        prefs=prefs,
    )


def _mountain_count_per_week(weeks):
    return [
        sum(1 for d in w['days']
            if d['workout_type'] in plan_engine.MOUNTAIN_WORKOUTS)
        for w in weeks
    ]


def test_per_week_budget_one_caps_mountain_workouts_to_one():
    prefs = {
        'max_weekly_km': 60, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
        'mountain_access_per_week': 1,
    }
    weeks = _gen(prefs, total_weeks=8)
    for c in _mountain_count_per_week(weeks):
        assert c <= 1


def test_per_week_budget_zero_downgrades_all_mountain_workouts():
    prefs = {
        'max_weekly_km': 60, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'flat_urban',
        'mountain_access_per_week': 0,
    }
    weeks = _gen(prefs, total_weeks=6)
    counts = _mountain_count_per_week(weeks)
    assert all(c == 0 for c in counts)


def test_per_month_budget_falls_back_to_weekly_division():
    prefs = {
        'max_weekly_km': 60, 'mountain_days': ['Saturday', 'Sunday'],
        'terrain_profile': 'rolling_hills',
        'mountain_access_per_month': 2,  # ~0.46/week
    }
    weeks = _gen(prefs, total_weeks=8)
    # per_month=2 / 4.33 = 0.46 → max 1 every ~2 weeks → at most 4 in 8 weeks.
    assert sum(_mountain_count_per_week(weeks)) <= 4


def test_no_prefs_back_compat_no_budget_enforced():
    weeks = _gen(None, total_weeks=4)
    # Without prefs, the engine has no mountain budget. We can't assert a specific
    # count, but we CAN assert the engine ran cleanly.
    assert len(weeks) == 4


def test_mountain_days_only_acts_as_calendar_mask_when_budget_absent():
    """Without per_week/per_month set, mountain_days acts as the budget (legacy fallback)."""
    prefs = {
        'max_weekly_km': 60, 'mountain_days': ['Saturday'],  # only one day
        'terrain_profile': 'rolling_hills',
    }
    weeks = _gen(prefs, total_weeks=4)
    for c in _mountain_count_per_week(weeks):
        # Budget = 1 (len(mountain_days))
        assert c <= 1

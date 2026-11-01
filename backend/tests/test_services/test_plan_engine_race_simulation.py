"""race_simulation must appear:
- on the long-run day of the LAST Peak week (dress rehearsal)
- on the long-run day of the Race week
…and nowhere else.
"""
from services.plan_engine import assign_phases, generate_plan


def test_race_simulation_only_in_peak_last_and_race_week():
    total_weeks = 12
    weeks = generate_plan(
        total_weeks=total_weeks,
        race_distance_km=50,
        race_elevation_m=2500,
        race_date='2026-08-01',
        athlete_weekly_km=45,
        athlete_weekly_elev=1500,
        athlete_longest_run_km=24,
        athlete_category='cat_2',
        long_run_day='Saturday',
        rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    phases = assign_phases(total_weeks, 'cat_2')
    peak_indices = [i for i, p in enumerate(phases) if p == 'Peak']
    assert peak_indices, "test fixture must include at least one Peak week"
    last_peak_idx = max(peak_indices)
    race_idx = total_weeks - 1

    for i, w in enumerate(weeks):
        types = [d['workout_type'] for d in w['days']]
        if i == last_peak_idx or i == race_idx:
            assert 'race_simulation' in types, (
                f"week {i+1} ({phases[i]}) is missing race_simulation"
            )
        else:
            assert 'race_simulation' not in types, (
                f"week {i+1} ({phases[i]}) has unexpected race_simulation"
            )

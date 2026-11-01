"""When back_to_back=True, a hard session sits the day before the long_run."""
from services.plan_engine import HARD_WORKOUTS, generate_plan


def test_back_to_back_pattern():
    weeks = generate_plan(
        total_weeks=10,
        race_distance_km=80,
        race_elevation_m=4000,
        race_date='2026-08-01',
        athlete_weekly_km=60,
        athlete_weekly_elev=2000,
        athlete_longest_run_km=35,
        athlete_category='cat_2',
        long_run_day='Sunday',
        rest_days=['Monday'],
        back_to_back=True,
        prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain'},
    )

    # Find at least one Build/Peak week with the pattern
    found = False
    for w in weeks:
        theme = w.get('theme', '').lower()
        if not (theme.startswith('build') or theme.startswith('peak')):
            continue
        days = {d['day']: d['workout_type'] for d in w['days']}
        # Saturday before the Sunday long_run should be a hard effort.
        if days.get('Sunday') == 'long_run' and days.get('Saturday') in HARD_WORKOUTS:
            found = True
            break
    assert found, "no Build/Peak week shows the back_to_back pattern"

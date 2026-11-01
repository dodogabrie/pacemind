"""When mountain budget forces a high downgrade ratio of mountain workouts,
validate_plan_feasibility must surface a 'mountain_specificity_lost' warning.
"""
from services.plan_engine import generate_plan, validate_plan_feasibility


def test_mountain_specificity_warning_when_budget_low():
    prefs = {
        'max_weekly_km': 100,
        'terrain_profile': 'mountain',
        'mountain_access_per_week': 0.5,  # very limited access
    }
    weeks = generate_plan(
        total_weeks=12,
        race_distance_km=80,
        race_elevation_m=5000,
        race_date='2026-08-01',
        athlete_weekly_km=60,
        athlete_weekly_elev=2500,
        athlete_longest_run_km=30,
        athlete_category='cat_2',
        long_run_day='Saturday',
        rest_days=['Monday'],
        prefs=prefs,
    )
    warnings = validate_plan_feasibility(
        weeks,
        prefs=prefs,
        terrain_profile='mountain',
        race_distance_km=80,
        race_elevation_m=5000,
    )
    codes = [w.get('code') for w in warnings if isinstance(w, dict)]
    issues = [w.get('issue') for w in warnings if isinstance(w, dict)]
    assert 'mountain_specificity_lost' in codes or 'mountain_specificity_lost' in issues

"""Audit-pass regression tests for plan_engine bug fixes (Session 6).

Covers:
  - apply_key_sections: descent annotation must be once per week, not once per plan
  - apply_key_sections: Base hill_repeats must use 6 reps (theme starts with "Base")
  - constants WEEKLY_MIN_LR_MULTIPLIER / BUILD_MIN_LR_MULTIPLIER / PEAK_MIN_LR_MULTIPLIER
    are honored as the minimum multiplier in the corresponding phase
"""

from services import plan_engine
from services.plan_engine import (
    BUILD_MIN_LR_MULTIPLIER,
    PEAK_MIN_LR_MULTIPLIER,
    WEEKLY_MIN_LR_MULTIPLIER,
    apply_key_sections,
)


def _make_week(theme, day_workouts):
    """Helper: build a week dict with given theme and a day per workout type."""
    days = []
    for i, wt in enumerate(day_workouts):
        days.append({
            'day': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i],
            'workout_type': wt,
            'title': '',
            'notes': '',
        })
    return {'theme': theme, 'days': days}


def test_apply_key_sections_descent_annotation_per_week_not_per_plan():
    """Bug fix: previously `descents = []` rebound the outer name, so once any
    week annotated an easy day, no other week ever did. The intent (per the
    code comment) is one annotation *per week*."""
    weeks = [
        _make_week('Build — increasing specificity',
                   ['easy', 'easy', 'rest', 'easy', 'rest', 'long_run', 'rest']),
        _make_week('Build — increasing specificity',
                   ['easy', 'easy', 'rest', 'easy', 'rest', 'long_run', 'rest']),
        _make_week('Peak — race-specific intensity',
                   ['easy', 'easy', 'rest', 'easy', 'rest', 'long_run', 'rest']),
    ]
    key_sections = [{'type': 'steep_descent', 'km_start': 20, 'km_end': 25}]

    apply_key_sections(weeks, key_sections)

    annotated_per_week = [
        sum(1 for d in w['days'] if d['notes'] == 'Include controlled descent practice')
        for w in weeks
    ]
    # Each of the 3 weeks should have exactly one annotation, not just the first.
    assert annotated_per_week == [1, 1, 1], (
        f"Expected one annotation per week, got {annotated_per_week}"
    )


def test_apply_key_sections_base_hill_repeats_uses_6_reps():
    """Bug fix: previously `week.get('theme') == 'Base'` was always false because
    themes are full strings like 'Base — aerobic foundation', so Base weeks
    silently received 8 reps instead of 6."""
    base_week = _make_week(
        'Base — aerobic foundation',
        ['easy', 'hill_repeats', 'rest', 'easy', 'rest', 'long_run', 'rest'],
    )
    build_week = _make_week(
        'Build — increasing specificity',
        ['easy', 'hill_repeats', 'rest', 'easy', 'rest', 'long_run', 'rest'],
    )
    key_sections = [{
        'type': 'steep_climb', 'km_start': 5, 'distance_km': 1.0, 'avg_grade_pct': 12,
    }]

    for w in (base_week, build_week):  # realistic engine titles (coach-review #111)
        for d in w['days']:
            ph = 'Base' if w is base_week else 'Build'
            d['title'] = plan_engine._generate_title(d['workout_type'], ph, 9, 280)
    apply_key_sections([base_week, build_week], key_sections)

    base_title = next(d['title'] for d in base_week['days']
                      if d['workout_type'] == 'hill_repeats')
    build_title = next(d['title'] for d in build_week['days']
                       if d['workout_type'] == 'hill_repeats')

    assert '6x' in base_title, f"Base hill_repeats should use 6 reps, got: {base_title}"
    assert '8x' in build_title, f"Build hill_repeats should use 8 reps, got: {build_title}"


def test_apply_key_sections_no_descents_leaves_notes_alone():
    """Sanity: if there are no steep_descent sections, no notes are added."""
    weeks = [_make_week('Build — increasing specificity', ['easy'] * 7)]
    apply_key_sections(weeks, [{'type': 'steep_climb', 'km_start': 5,
                                'distance_km': 1.0, 'avg_grade_pct': 10}])
    notes = [d['notes'] for d in weeks[0]['days']]
    assert all(n == '' for n in notes)


def test_lr_multiplier_constants_used_in_compute_weekly_targets():
    """Regression: previously the literals 1.6 / 2.0 / 1.7 were hardcoded
    in the Base/Build/Peak branches of compute_weekly_targets. After the
    fix they must come from the named constants so changes to the constant
    actually take effect.

    To isolate the per-phase floor from the 10%-week-over-week cap (which
    only restores `WEEKLY_MIN_LR_MULTIPLIER`), we run each phase as the
    only progression week so there's no prior week to cap against.
    """
    common = dict(
        athlete_weekly_km=10,         # tiny baseline -> LR floor dominates
        athlete_weekly_elev=200,
        athlete_longest_run_km=20,    # comparatively large -> LR drives weekly_km
        race_distance_km=30,
        race_elevation_m=900,
    )

    base_only = plan_engine.compute_weekly_targets(phases=['Base'], **common)[0]
    build_only = plan_engine.compute_weekly_targets(phases=['Build'], **common)[0]
    peak_only = plan_engine.compute_weekly_targets(phases=['Peak'], **common)[0]

    # weekly_km and long_run_km are independently rounded to 1 decimal,
    # so the multiplied bound carries up to ~0.15 km of error.
    assert base_only.weekly_km >= base_only.long_run_km * WEEKLY_MIN_LR_MULTIPLIER - 0.15
    assert build_only.weekly_km >= build_only.long_run_km * BUILD_MIN_LR_MULTIPLIER - 0.15
    assert peak_only.weekly_km >= peak_only.long_run_km * PEAK_MIN_LR_MULTIPLIER - 0.15


def test_compute_weekly_targets_smoke_realistic_plan():
    """Plan with 7 weeks should still produce 7 targets, in phase order, and
    every weekly_km should respect the global WEEKLY_MIN_LR_MULTIPLIER floor."""
    phases = plan_engine.assign_phases(7, 'cat_2')
    targets = plan_engine.compute_weekly_targets(
        phases=phases,
        athlete_weekly_km=55,
        athlete_weekly_elev=2100,
        athlete_longest_run_km=25,
        race_distance_km=50,
        race_elevation_m=3500,
    )
    assert len(targets) == 7
    for t in targets:
        if t.phase != 'Race' and t.long_run_km > 0:
            assert t.weekly_km >= t.long_run_km * WEEKLY_MIN_LR_MULTIPLIER - 0.15


def test_validate_plan_feasibility_mountain_budget_warning_still_fires():
    """Sanity: removing the dead `< float('inf')` guard must not change behavior
    for finite mountain_budget values."""
    prefs = {'mountain_access_per_week': 1, 'max_weekly_km': 60,
             'mountain_days': ['Saturday', 'Sunday']}
    weeks = [{
        'week_number': 1, 'theme': 'Build — increasing specificity',
        'total_km': 50, 'days': [
            {'day': 'Saturday', 'workout_type': 'hill_repeats',
             'distance_km': 10, 'elevation_m': 600},
            {'day': 'Sunday', 'workout_type': 'vert_session',
             'distance_km': 12, 'elevation_m': 800},
        ],
    }]
    warnings = plan_engine.validate_plan_feasibility(
        weeks, prefs, terrain_profile='mountain'
    )
    issues = {w['issue'] for w in warnings}
    assert 'mountain_budget_exceeded' in issues

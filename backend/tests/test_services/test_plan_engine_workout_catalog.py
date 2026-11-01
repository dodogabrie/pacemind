"""Catalog invariant: every workout type the engine emits must be fully
described in the constants tables (WORKOUT_KM_RANGE, ELEV_MULTIPLIER).
Catches the historical gap where 'tempo' was promised in the prompt but
never produced by the engine.
"""
import pytest

from services.plan_engine import (
    ELEV_MULTIPLIER,
    PHASE_CATALOG,
    WORKOUT_KM_RANGE,
    generate_plan,
)


def _emitted_types(weeks):
    return {d['workout_type'] for w in weeks for d in w['days']}


@pytest.mark.parametrize('category', ['cat_1', 'cat_2'])
@pytest.mark.parametrize('total_weeks', [4, 8, 12, 18])
def test_every_emitted_type_is_in_constants(category, total_weeks):
    weeks = generate_plan(
        total_weeks=total_weeks,
        race_distance_km=50,
        race_elevation_m=2500,
        race_date='2026-08-01',
        athlete_weekly_km=40,
        athlete_weekly_elev=1000,
        athlete_longest_run_km=22,
        athlete_category=category,
        long_run_day='Saturday',
        rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    types = _emitted_types(weeks)
    missing_km = types - set(WORKOUT_KM_RANGE.keys())
    missing_elev = types - set(ELEV_MULTIPLIER.keys())
    assert not missing_km, f"types missing from WORKOUT_KM_RANGE: {missing_km}"
    assert not missing_elev, f"types missing from ELEV_MULTIPLIER: {missing_elev}"


def test_phase_catalog_types_all_known():
    """No catalog entry references an unknown workout type."""
    all_known = set(WORKOUT_KM_RANGE.keys()) | {'rest'}
    for phase, catalog in PHASE_CATALOG.items():
        unknown = set(catalog) - all_known
        assert not unknown, f"phase {phase} catalog has unknown types: {unknown}"


def test_tempo_appears_in_build_or_peak():
    """Regression: tempo must be reachable in build/peak."""
    weeks = generate_plan(
        total_weeks=12,
        race_distance_km=42,
        race_elevation_m=1500,
        race_date='2026-08-01',
        athlete_weekly_km=50,
        athlete_weekly_elev=1200,
        athlete_longest_run_km=25,
        athlete_category='cat_2',
        long_run_day='Saturday',
        rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'rolling_hills'},
    )
    types = _emitted_types(weeks)
    assert 'tempo' in types, (
        f"engine never emitted 'tempo' — produced types: {sorted(types)}"
    )

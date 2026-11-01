"""Unit tests for the plan readiness gate."""

import pytest

from services.plan_engine import generate_plan
from services.plan_readiness import (
    ABSOLUTE_MIN_WEEKS,
    LR_STRETCH_MULTIPLIER,
    LR_UNREALISTIC_MULTIPLIER,
    assess_readiness,
    min_weeks_for_race,
)


# ---------------------------------------------------------------------------
# assess_readiness
# ---------------------------------------------------------------------------

def test_feasible_when_baseline_supports_race_and_window_is_long():
    v = assess_readiness(
        race_distance_km=42,
        available_weeks=16,
        athlete_longest_run_km=25,
        athlete_weekly_km=50,
        ctl=40,
    )
    assert v.status == 'feasible'
    assert v.reasons == []


def test_unrealistic_when_long_run_jump_above_4x():
    # 50 km race target ~37.5 km LR; baseline 5 km → ratio 7.5×
    v = assess_readiness(
        race_distance_km=50,
        available_weeks=24,
        athlete_longest_run_km=5,
        ctl=20,
    )
    assert v.status == 'unrealistic'
    assert any('long_run_jump_too_large' in r for r in v.reasons)
    assert v.long_run_jump_ratio > LR_UNREALISTIC_MULTIPLIER


def test_stretch_when_long_run_jump_between_2x_and_4x():
    # 50 km race target 37.5 km LR; baseline 15 km → ratio 2.5× → stretch
    v = assess_readiness(
        race_distance_km=50,
        available_weeks=24,
        athlete_longest_run_km=15,
        ctl=40,
    )
    assert v.status == 'stretch'
    assert v.long_run_jump_ratio > LR_STRETCH_MULTIPLIER
    assert v.long_run_jump_ratio <= LR_UNREALISTIC_MULTIPLIER


def test_unrealistic_when_window_far_below_min_weeks():
    # Solid baseline but only 2 weeks for a 50 km race → window too short.
    v = assess_readiness(
        race_distance_km=50,
        available_weeks=2,
        athlete_longest_run_km=25,
        ctl=40,
    )
    assert v.status == 'unrealistic'
    assert any('insufficient_weeks' in r for r in v.reasons)


def test_unrealistic_below_absolute_minimum_window():
    v = assess_readiness(
        race_distance_km=10,
        available_weeks=1,
        athlete_longest_run_km=8,
        ctl=20,
    )
    assert v.status == 'unrealistic'
    assert any('plan_window_too_short' in r for r in v.reasons)
    assert ABSOLUTE_MIN_WEEKS == 2


def test_stretch_when_ctl_just_below_target():
    # 90 km ultra → CTL target ~19.3; CTL=14 (73%) → stretch.
    v = assess_readiness(
        race_distance_km=90,
        available_weeks=24,
        athlete_longest_run_km=50,
        ctl=14,
    )
    assert v.status == 'stretch'
    assert any('chronic_load_below_target' in r for r in v.reasons)


def test_unrealistic_when_ctl_far_below_target():
    # 90 km ultra → CTL target ~19.3; CTL=8 (41%) → unrealistic.
    v = assess_readiness(
        race_distance_km=90,
        available_weeks=24,
        athlete_longest_run_km=50,
        ctl=8,
    )
    assert v.status == 'unrealistic'
    assert any('low_chronic_load' in r for r in v.reasons)


def test_fit_athlete_not_refused_for_34km_race():
    # #109: 75 km/wk + 3000 m D+/wk = ~15 km-effort/day (user 3 read 11).
    v = assess_readiness(
        race_distance_km=34,
        available_weeks=15,
        athlete_longest_run_km=45,
        ctl=11,
    )
    assert v.status == 'feasible'


def test_ewma_steady_load_reads_as_itself():
    from services.training_load_service import TrainingLoadService
    daily = {d: 10.0 for d in range(60)}
    assert TrainingLoadService()._ewma(daily, 42) == pytest.approx(10.0, rel=0.01)


def test_unknown_baseline_does_not_throw():
    v = assess_readiness(
        race_distance_km=21,
        available_weeks=12,
        athlete_longest_run_km=0,
    )
    assert v.status in ('feasible', 'stretch', 'unrealistic')
    assert any('long_run_baseline_unknown' in r for r in v.reasons)


# ---------------------------------------------------------------------------
# min_weeks_for_race
# ---------------------------------------------------------------------------

def test_min_weeks_grows_with_distance_for_low_baseline():
    short = min_weeks_for_race(21, athlete_longest_run_km=10)
    long_ = min_weeks_for_race(100, athlete_longest_run_km=10)
    assert long_ > short
    assert short >= ABSOLUTE_MIN_WEEKS


def test_min_weeks_short_when_already_at_target():
    # Athlete with LR ≥ peak target (race 30 km × 0.75 = 22.5 → LR 30 already
    # past it). Only base + taper + race week needed.
    weeks = min_weeks_for_race(30, athlete_longest_run_km=30)
    # Already at LR target → just base + taper + race week (~7).
    assert weeks <= 8


# ---------------------------------------------------------------------------
# Long-run cap from baseline (plan_engine integration)
# ---------------------------------------------------------------------------

def _peak_long_run_excluding_race_week(weeks):
    """Largest long_run/race_simulation in the plan, ignoring race week
    (always the last week of the plan)."""
    candidates = [
        d['distance_km']
        for w in weeks[:-1]
        for d in w['days']
        if d['workout_type'] in ('long_run', 'race_simulation')
    ]
    return max(candidates) if candidates else 0.0


def test_engine_breaks_long_run_plateau_with_stepback():
    """No more than ``LR_MAX_PLATEAU_LENGTH+1`` consecutive Build/Peak
    weeks should sit at the same long-run distance. Coaching consensus
    (Higdon, MyProCoach, Koop, INOV8): 100 km builds wave between peak
    LR weeks and stepback weeks at ~70 % of peak — never a flat plateau
    of 4-5 weeks."""
    from services.plan_engine import (
        LR_MAX_PLATEAU_LENGTH, LR_PLATEAU_TOLERANCE_KM,
    )
    weeks = generate_plan(
        total_weeks=16,
        race_distance_km=100, race_elevation_m=5000,
        race_date='2026-08-22',
        athlete_weekly_km=70, athlete_weekly_elev=1800,
        athlete_longest_run_km=42, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Monday'],
        prefs={'max_weekly_km': 110, 'terrain_profile': 'mountain'},
    )

    # Walk Build/Peak weeks (everything but Base/Recovery/Taper/Race),
    # count consecutive plateau weeks.
    long_runs: list[tuple[int, str, float]] = []
    for w in weeks:
        theme = w.get('theme', '')
        lr = next(
            (d['distance_km'] for d in w['days']
             if d['workout_type'] in ('long_run', 'race_simulation')),
            0.0,
        )
        long_runs.append((w['week_number'], theme, lr))

    plateau = 0
    prev_lr = None
    for i, (wn, theme, lr) in enumerate(long_runs):
        # A deload week right after is itself the cutback (no double deload, #115).
        nxt = long_runs[i + 1][1] if i + 1 < len(long_runs) else ''
        ends_in_deload = not ('Build' in nxt or 'Peak' in nxt)
        if 'Build' in theme or 'Peak' in theme:
            if prev_lr is not None and abs(lr - prev_lr) <= LR_PLATEAU_TOLERANCE_KM:
                plateau += 1
            else:
                plateau = 0
            assert plateau <= LR_MAX_PLATEAU_LENGTH + (1 if ends_in_deload else 0), (
                f"week {wn}: plateau ran for {plateau + 1} consecutive "
                f"Build/Peak weeks at LR={lr} km — wave/cutback missing"
            )
            prev_lr = lr
        else:
            prev_lr = None
            plateau = 0


def test_engine_peak_long_run_follows_race_target_for_capable_athlete():
    """An athlete already past the LR-progression target should see the
    peak LR set by the race target (60-80 % of race distance), per
    Higdon / Koop / CTS coaching consensus — not artificially capped to
    a baseline multiplier."""
    weeks = generate_plan(
        total_weeks=16,
        race_distance_km=50, race_elevation_m=2000,
        race_date='2026-08-01',
        athlete_weekly_km=70, athlete_weekly_elev=2000,
        athlete_longest_run_km=30, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Friday'],
        prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain'},
    )
    peak_lr = _peak_long_run_excluding_race_week(weeks)
    # Race target: 50 × 0.75 = 37.5 km. Allow some slack for the 10 %
    # week-over-week cap and rounding.
    assert 30 <= peak_lr <= 40

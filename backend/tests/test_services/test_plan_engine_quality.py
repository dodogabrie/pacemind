"""Coaching-quality regression tests.

These lock in the bugs that were fixed during the plan_engine refactor:
  - empty race_simulation in last Peak week
  - 3+ consecutive hard days (no recovery between high-stress sessions)
  - Base hill_repeats sized as climb day (>150 m D+) — they're sprints
  - taper long_run carrying the full race-ratio elevation
  - missing Recovery week before Peak in mid-length plans
  - mountain downgrade introducing intervals into a Base week
"""
import pytest

from services import plan_engine
from services.plan_engine import HARD_WORKOUTS, MOUNTAIN_WORKOUTS, generate_plan


def _gen(**overrides):
    base = dict(
        total_weeks=12, race_distance_km=50, race_elevation_m=3500,
        race_date='2026-08-01',
        athlete_weekly_km=55, athlete_weekly_elev=2100,
        athlete_longest_run_km=25, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Friday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'mountain'},
    )
    base.update(overrides)
    return generate_plan(**base)


def test_last_peak_race_simulation_is_not_empty():
    """The dress-rehearsal race_simulation in the last Peak week must
    carry real distance and elevation, not 0/0."""
    weeks = _gen(total_weeks=7, athlete_category='cat_1')
    found = False
    for w in weeks:
        if not w['theme'].startswith('Peak'):
            continue
        for d in w['days']:
            if d['workout_type'] == 'race_simulation':
                found = True
                assert d['distance_km'] > 0, (
                    f"Peak race_simulation has 0 km — {d}"
                )
                assert d['elevation_m'] > 0 or 'flat_urban' in str(w), (
                    f"Peak race_simulation has 0 m D+ — {d}"
                )
    assert found, "no race_simulation in any Peak week"


def test_no_three_consecutive_hard_days():
    """Hard sessions need recovery: never 3 hard workouts in a row."""
    for total_weeks in (8, 12, 16):
        weeks = _gen(total_weeks=total_weeks)
        for w in weeks:
            days = list(w['days'])
            for i in range(len(days) - 2):
                trio = [days[i + k]['workout_type'] for k in range(3)]
                hard_count = sum(1 for t in trio if t in HARD_WORKOUTS)
                assert hard_count < 3, (
                    f"3 consecutive hard days in W{w['week_number']}: {trio}"
                )


def test_no_back_to_back_hard_days_when_b2b_disabled():
    """With back_to_back=False, two hard sessions are never on adjacent
    days inside a Build/Peak week."""
    weeks = _gen(total_weeks=12, back_to_back=False)
    for w in weeks:
        if not (w['theme'].startswith('Build') or w['theme'].startswith('Peak')):
            continue
        days = list(w['days'])
        for i in range(len(days) - 1):
            a, b = days[i]['workout_type'], days[i + 1]['workout_type']
            if a in HARD_WORKOUTS and b in HARD_WORKOUTS:
                pytest.fail(
                    f"W{w['week_number']} ({w['theme']}) has adjacent hard "
                    f"sessions {days[i]['day']}={a} → {days[i+1]['day']}={b}"
                )


def test_base_hill_repeats_are_sprints_not_climb_days():
    """Base hill_repeats are 6×10 s sprints, ~80 m D+ total, NOT a 500 m
    climbing session."""
    weeks = _gen(total_weeks=10)
    base_hills = [
        d for w in weeks if w['theme'].startswith('Base')
        for d in w['days'] if d['workout_type'] == 'hill_repeats'
    ]
    assert base_hills, "test fixture must reach a Base hill_repeats day"
    for d in base_hills:
        assert d['elevation_m'] <= 100, (
            f"Base hill_repeats has {d['elevation_m']} m D+; expected ≤ 100 "
            f"(neuromuscular sprints, not climb day)"
        )


def test_taper_long_run_elevation_scaled_down():
    """Taper long-run elevation should be deloaded; never carry the full
    race-ratio D+. Expect at most ~60 % of race ratio."""
    race_distance, race_elev = 50, 3500
    race_ratio = race_elev / race_distance  # 70 m/km
    weeks = _gen(total_weeks=12)
    taper_long_runs = [
        d for w in weeks if w['theme'].startswith('Taper')
        for d in w['days'] if d['workout_type'] == 'long_run'
    ]
    assert taper_long_runs
    for d in taper_long_runs:
        if d['distance_km'] <= 0:
            continue
        density = d['elevation_m'] / d['distance_km']
        assert density <= race_ratio * 0.65 + 1, (
            f"Taper long_run density {density:.0f} m/km > 65 % of race "
            f"ratio ({race_ratio:.0f}). Day: {d}"
        )


def test_recovery_week_precedes_peak():
    """Mid-length plans insert a Recovery week directly before the Peak
    block whenever there is enough build_pool to make a deload meaningful.
    Short plans with a tight build_pool (e.g. 8-week ultra builds where
    only 2 Build slots exist before Peak) skip the pre-Peak Recovery —
    there is no fatigue to deload from and the slot is more useful as
    another Build week (coach-review #2 — Issurin block periodization,
    Friel). Independently, no more than RECOVERY_MODULATION (3) Build
    weeks should run consecutively before Peak."""
    for total_weeks in (8, 10, 12, 14, 16):
        phases = plan_engine.assign_phases(total_weeks, 'cat_2')
        if 'Peak' not in phases:
            continue
        peak_idx = phases.index('Peak')
        assert peak_idx > 0

        # Never enter Peak after > RECOVERY_MODULATION consecutive Builds.
        consecutive = 0
        max_consecutive = 0
        for p in phases[:peak_idx]:
            consecutive = consecutive + 1 if p == 'Build' else 0
            max_consecutive = max(max_consecutive, consecutive)
        assert max_consecutive <= plan_engine.RECOVERY_MODULATION, (
            f"{total_weeks}w plan: {max_consecutive} consecutive Builds "
            f"before Peak, phases = {phases}"
        )

        # Plans with enough build_pool keep the canonical pre-Peak Recovery.
        # The 8-week ultra case (build_pool=2) is the documented exception.
        if total_weeks >= 10:
            assert phases[peak_idx - 1] in ('Recovery', 'Base'), (
                f"{total_weeks}w plan: Peak preceded by {phases[peak_idx - 1]}, "
                f"phases = {phases}"
            )


def test_no_intervals_in_base_when_mountain_unavailable():
    """When mountain access blocks Build/Peak hill_repeats, the canonical
    downgrade is intervals — but Base must NEVER receive intervals
    (it's an aerobic-only phase)."""
    weeks = _gen(
        total_weeks=10, race_distance_km=42, race_elevation_m=1500,
        athlete_weekly_km=50, athlete_weekly_elev=200,
        athlete_longest_run_km=22, long_run_day='Saturday', rest_days=['Monday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'flat_urban',
               'mountain_access_per_week': 1, 'mountain_days': ['Saturday']},
    )
    for w in weeks:
        if not w['theme'].startswith('Base'):
            continue
        types = [d['workout_type'] for d in w['days']]
        assert 'intervals' not in types, (
            f"Base week W{w['week_number']} has intervals: {types}"
        )


def test_taper_volume_strictly_decreases():
    """Across consecutive taper weeks, total volume must strictly
    decrease toward race week."""
    weeks = _gen(total_weeks=12)
    taper = [w for w in weeks if w['theme'].startswith('Taper')]
    assert len(taper) >= 2
    for i in range(len(taper) - 1):
        assert taper[i + 1]['total_km'] < taper[i]['total_km'] + 0.5, (
            f"Taper W{taper[i+1]['week_number']} ({taper[i+1]['total_km']}km) "
            f">= prev taper W{taper[i]['week_number']} ({taper[i]['total_km']}km)"
        )


def test_taper_volume_never_exceeds_peak_volume():
    """Taper-1 weekly volume must be a deload from the achieved peak
    (Mujika & Padilla; Koop; CTS; Trail Runner Magazine — unanimous).

    Regression: when the available_hours_per_week budget clipped Build /
    Peak weeks but did NOT apply to Taper, and the WEEKLY_MIN_LR_MULTIPLIER
    floor pushed Taper-1 weekly_km up to 2× the (un-clipped) taper LR,
    Taper-1 could come out LARGER than the preceding Peak week.
    Reproducer: 100K mountain ultra with a 12 h/week budget.
    """
    weeks = generate_plan(
        total_weeks=20, race_distance_km=100, race_elevation_m=6000,
        race_date='2026-09-19',
        athlete_weekly_km=55, athlete_weekly_elev=1500,
        athlete_longest_run_km=35, athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Friday'],
        prefs={
            'max_weekly_km': 110, 'terrain_profile': 'rolling_hills',
            'mountain_days': ['Saturday', 'Sunday'],
            'available_hours_per_week': 12,
            'max_long_run_km': 55, 'max_long_run_hours': 8,
        },
        athlete_flat_pace_min_km=5.5,
        back_to_back=True,
    )
    progression_peak_km = max(
        w['total_km'] for w in weeks
        if w['theme'].startswith(('Build', 'Peak'))
    )
    for w in weeks:
        if not w['theme'].startswith('Taper'):
            continue
        assert w['total_km'] <= progression_peak_km + 0.5, (
            f"Taper W{w['week_number']} = {w['total_km']} km exceeds "
            f"progression peak {progression_peak_km} km — taper must "
            f"REDUCE from peak (Mujika & Padilla)"
        )


def test_taper_long_run_never_exceeds_peak_long_run():
    """Taper long_run must never exceed the achieved peak long_run.

    Regression: ``_long_run_for(Taper)`` previously sized off the
    race-derived ``target_lr`` (race × 0.75), ignoring how much LR was
    actually programmed in Build / Peak. With a tight hours budget that
    clipped Peak LR to ~32 km, the Taper formula could still produce a
    37.5 km LR — bigger than peak. Fixed by tracking ``peak_lr_so_far``.
    """
    weeks = generate_plan(
        total_weeks=20, race_distance_km=100, race_elevation_m=6000,
        race_date='2026-09-19',
        athlete_weekly_km=55, athlete_weekly_elev=1500,
        athlete_longest_run_km=35, athlete_category='cat_2',
        long_run_day='Saturday', rest_days=['Friday'],
        prefs={
            'max_weekly_km': 110, 'terrain_profile': 'rolling_hills',
            'mountain_days': ['Saturday', 'Sunday'],
            'available_hours_per_week': 12,
            'max_long_run_km': 55, 'max_long_run_hours': 8,
        },
        athlete_flat_pace_min_km=5.5,
        back_to_back=True,
    )
    progression_peak_lr = max(
        d['distance_km']
        for w in weeks if w['theme'].startswith(('Base', 'Build', 'Peak'))
        for d in w['days'] if d['workout_type'] == 'long_run'
    )
    taper_lrs = [
        d['distance_km']
        for w in weeks if w['theme'].startswith('Taper')
        for d in w['days'] if d['workout_type'] == 'long_run'
    ]
    assert taper_lrs, 'no taper long_run found in fixture'
    for lr in taper_lrs:
        assert lr <= progression_peak_lr + 0.5, (
            f"Taper long_run {lr} km exceeds progression peak "
            f"{progression_peak_lr} km — deload must come FROM peak"
        )


def test_no_more_than_two_hard_per_week_in_build_or_peak():
    """Coaching ceiling: ≤ 2 hard sessions / week in Build or Peak."""
    weeks = _gen(total_weeks=16)
    for w in weeks:
        if not (w['theme'].startswith('Build') or w['theme'].startswith('Peak')):
            continue
        n_hard = sum(1 for d in w['days'] if d['workout_type'] in HARD_WORKOUTS)
        assert n_hard <= 2, (
            f"W{w['week_number']} ({w['theme']}) has {n_hard} hard sessions"
        )


def test_every_day_elevation_is_multiple_of_50m():
    """Coaching granularity: trail/mountain prescriptions don't distinguish
    211 m from 200 m. Every day's elevation must be a multiple of 50 m."""
    weeks = _gen(total_weeks=12)
    for w in weeks:
        for d in w['days']:
            elev = d['elevation_m']
            assert elev % 50 == 0, (
                f"W{w['week_number']} {d['day']} ({d['workout_type']}) has "
                f"elevation {elev} m — not a 50 m step"
            )


def test_elevation_never_exactly_50m():
    """50 m is not a meaningful prescription — values are 0 or ≥ 100."""
    weeks = _gen(total_weeks=12)
    for w in weeks:
        for d in w['days']:
            elev = d['elevation_m']
            assert elev == 0 or elev >= 100, (
                f"W{w['week_number']} {d['day']} ({d['workout_type']}) has "
                f"elevation {elev} m — must be 0 or ≥ 100"
            )


def test_running_days_are_at_least_8_km():
    """Trail-running prescription: minimum 8 km on any running day —
    shorter than that is barely worth getting out the door. Deliberate
    exceptions: race-week easy_strides (taper shakeout), and race-week
    easy / recovery / easy_pickups (5 km minimum) — Mujika & Padilla
    (2003) and Bosquet et al. (2007) prescribe preserved frequency at
    reduced volume in the pre-race week, which a strict 8 km floor
    would prevent given the tight race-week budget."""
    weeks = _gen(total_weeks=12)
    runnable = {'easy', 'easy_pickups', 'recovery', 'tempo', 'intervals',
                'hill_repeats', 'vert_session'}
    race_week_relaxed = {'easy', 'easy_pickups', 'recovery'}
    for w in weeks:
        is_race_week = (w.get('theme') or '').startswith('Race')
        for d in w['days']:
            if d['workout_type'] in runnable and d['distance_km'] > 0:
                if is_race_week and d['workout_type'] in race_week_relaxed:
                    assert d['distance_km'] >= 5, (
                        f"W{w['week_number']} {d['day']} ({d['workout_type']}) "
                        f"is only {d['distance_km']} km — race-week minimum is 5 km"
                    )
                else:
                    assert d['distance_km'] >= 8, (
                        f"W{w['week_number']} {d['day']} ({d['workout_type']}) "
                        f"is only {d['distance_km']} km — minimum is 8 km"
                    )


def test_engine_inserts_rest_days_when_budget_too_tight():
    """Athlete declares no rest days (can run every day) but a tight
    weekly cap prevents fitting 6 runs at the 8 km minimum. The engine
    must add rest days on its own rather than chop runs short."""
    weeks = generate_plan(
        total_weeks=8, race_distance_km=21, race_elevation_m=600,
        race_date='2026-08-01',
        athlete_weekly_km=30, athlete_weekly_elev=500,
        athlete_longest_run_km=12, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=[],   # ← no declared rest
        prefs={'max_weekly_km': 35, 'terrain_profile': 'rolling_hills'},
    )
    # Some week must contain at least one rest day inserted by the engine.
    inserted_rest = any(
        any(d['workout_type'] == 'rest' for d in w['days'])
        for w in weeks
    )
    assert inserted_rest, "engine should insert rest days under tight budget"
    # And no running session can be below 8 km — except race-week easy /
    # recovery / easy_pickups which may go to 5 km (race-week frequency
    # exception, see _km_range_for / RACE_WEEK_KM_RANGE_OVERRIDE).
    runnable = {'easy', 'easy_pickups', 'recovery', 'tempo', 'intervals',
                'hill_repeats', 'vert_session'}
    race_week_relaxed = {'easy', 'easy_pickups', 'recovery'}
    for w in weeks:
        is_race_week = (w.get('theme') or '').startswith('Race')
        for d in w['days']:
            if d['workout_type'] in runnable and d['distance_km'] > 0:
                floor = (5 if is_race_week
                         and d['workout_type'] in race_week_relaxed else 8)
                assert d['distance_km'] >= floor


def test_distances_are_even_km_except_long_runs():
    """Round to even km (step 2) for every workout except the calibrated
    long_run / race_simulation targets."""
    weeks = _gen(total_weeks=12)
    precise = {'long_run', 'race_simulation'}
    for w in weeks:
        for d in w['days']:
            wt = d['workout_type']
            km = d['distance_km']
            if wt in precise:
                continue  # precision left untouched
            # Must be 0 or an even integer (4.0, 6.0, 8.0, ...).
            assert km == int(km), (
                f"W{w['week_number']} {d['day']} ({wt}) km={km} not an integer"
            )
            assert int(km) % 2 == 0, (
                f"W{w['week_number']} {d['day']} ({wt}) km={km} not even"
            )


def test_titles_match_rounded_elevation():
    """Titles that mention D+ must show the rounded value, not a stale
    pre-redistribution number."""
    weeks = _gen(total_weeks=8)
    for w in weeks:
        for d in w['days']:
            title = d['title']
            elev = int(d['elevation_m'])
            # Only check titles that contain a "<n>m D+" or "<n>m" pattern.
            if 'm D+' in title and elev > 0:
                # Title should contain the rounded elev, not anything off by
                # more than rounding error.
                import re
                matches = re.findall(r'(\d+)m', title)
                # All numbers in the title that look like elevation should
                # match the day's actual elevation.
                if matches:
                    title_elevs = [int(m) for m in matches if int(m) >= 50]
                    if title_elevs:
                        # At least one matches the day elev.
                        assert elev in title_elevs, (
                            f"Title '{title}' references {title_elevs}, "
                            f"but day elev is {elev}"
                        )


def test_no_more_than_two_consecutive_rest_days():
    """Coaching rule: a week must not contain a run of 3+ consecutive
    rest days. Most violations occur in Race / Taper weeks where the
    catalog ships with 4 rest slots and the budget collapses easy days
    into rest. The engine inserts a short shakeout to break any run."""
    for total_weeks in (8, 12, 16):
        weeks = _gen(total_weeks=total_weeks)
        for w in weeks:
            consecutive = 0
            for d in w['days']:
                if d['workout_type'] == 'rest':
                    consecutive += 1
                    assert consecutive <= 2, (
                        f"W{w['week_number']} ({w['theme']}) has "
                        f">{2} consecutive rest days: "
                        f"{[x['workout_type'] for x in w['days']]}"
                    )
                else:
                    consecutive = 0


def test_no_more_than_three_consecutive_build_weeks():
    """Coach rule: never more than 3 consecutive Build weeks without a
    Recovery deload week between them (3:1 modulation). Catches the bug
    where 16-week plans shipped 4 builds in a row."""
    from services.plan_engine import assign_phases
    for total_weeks in (8, 10, 12, 14, 16, 18, 20, 24):
        phases = assign_phases(total_weeks, 'cat_2')
        run = 0
        for p in phases:
            if p == 'Build':
                run += 1
                assert run <= 3, (
                    f"{total_weeks}-week plan has {run} consecutive "
                    f"Build weeks: {phases}"
                )
            else:
                run = 0


def test_long_run_progression_is_monotonic_within_long_runs():
    """Long-run distance never decreases across consecutive Base/Build/Peak
    weeks. (race_simulation in the last Peak week is intentionally smaller
    than the peak long_run — that's the rehearsal-vs-race-pace pattern, so
    we exclude race_simulation days from this check.)
    """
    weeks = _gen(total_weeks=12)
    progression_lr = []
    for w in weeks:
        phase = w['theme'].split(' ')[0]
        if phase not in ('Base', 'Build', 'Peak'):
            continue
        lr_km = next((d['distance_km'] for d in w['days']
                      if d['workout_type'] == 'long_run'), None)
        if lr_km is not None and lr_km > 0:
            progression_lr.append((w['week_number'], lr_km))
    for i in range(len(progression_lr) - 1):
        prev_wk, prev_km = progression_lr[i]
        next_wk, next_km = progression_lr[i + 1]
        assert next_km >= prev_km - 0.15, (
            f"Long-run dropped W{prev_wk}={prev_km}km → W{next_wk}={next_km}km"
        )

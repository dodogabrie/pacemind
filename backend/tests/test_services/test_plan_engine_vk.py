"""Coaching-quality regression tests for VK / uphill_only races.

Locks in the fixes for short uphill races (Vertical Kilometer, ~5 km / 1000 m
D+, ~30-90 min sustained climbing). Before these fixes the engine treated VK
as a tiny road race:

  - long_run target = race_distance × 0.75 = 3.75 km, REGRESSING the athlete's
    aerobic base instead of building it (Vert.run / Suunto / Lavedrine 2024
    prescribe 1.5-2.5 h aerobic mountain time as the central VK stimulus).
  - regime weekend cap (designed for marathon/ultra) trimmed Saturday hill
    workouts to ``easy``, killing the canonical Sat-hill + Sun-long-mountain
    weekend stack.
  - back_to_back default off blocked hill_repeats from landing on the only
    mountain training day (Sat).
  - no auto-strength (auto-strength only triggered for ≥50 km / 1500 m D-),
    despite Vert.run / Suunto explicitly prescribing weekly leg strength for
    short uphill races.
  - Build phase used flat ``tempo`` instead of ``hill_repeats`` for an
    all-uphill race.
"""
import pytest

from services.plan_engine import HARD_WORKOUTS, MOUNTAIN_WORKOUTS, generate_plan


def _gen_vk(**overrides):
    """Generate a 10-week VK 5 km / 1000 m D+ plan."""
    base = dict(
        total_weeks=10, race_distance_km=5.0, race_elevation_m=1000.0,
        race_date='2026-07-12',
        athlete_weekly_km=35.0, athlete_weekly_elev=800.0,
        athlete_longest_run_km=12.0, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Friday'],
        race_type='uphill_only',
        prefs={
            'max_weekly_km': 50, 'terrain_profile': 'mountain',
            'mountain_days': ['Saturday', 'Sunday'],
            'mountain_access_per_week': 2,
        },
    )
    base.update(overrides)
    return generate_plan(**base)


def test_vk_long_run_preserves_aerobic_base():
    """Build/Peak long-run must NOT collapse below the athlete's existing
    longest run. Race × 0.75 = 3.75 km is shorter than the 12 km baseline,
    which would detrain the aerobic base. The UPHILL_ONLY_LR_GROWTH override
    floors the target at 1.25 × athlete_longest_run_km = 15 km."""
    weeks = _gen_vk()
    for w in weeks:
        if not w['theme'].startswith(('Build', 'Peak')):
            continue
        long_runs = [d for d in w['days'] if d['workout_type'] == 'long_run']
        if not long_runs:
            continue
        lr = long_runs[0]
        # Floor: at minimum 7 km (≥ 60 % of athlete_longest_run_km=12 km).
        # Without the fix the LR collapsed to ≤ 4 km.
        assert lr['distance_km'] >= 7.0, (
            f"W{w['week_number']} ({w['theme']}): long_run="
            f"{lr['distance_km']} km — VK plan is detraining aerobic base "
            f"(athlete_longest_run_km=12). Expected ≥ 7 km."
        )


def test_vk_has_weekly_strength_session():
    """Auto-strength must trigger for ``uphill_only`` races regardless of
    distance. Vert.run, Suunto and Lavedrine 2024 all prescribe a weekly
    leg-strength routine (squats, lunges, calf raises, step-downs) for
    short uphill races — same physiology as ultra descents but on the
    concentric / isometric side."""
    weeks = _gen_vk()
    strength_weeks = [
        w for w in weeks
        if any(d['workout_type'] == 'strength' for d in w['days'])
        and not w['theme'].startswith(('Race', 'Taper'))
    ]
    # At least Base + 3 Build + Recovery + 2 Peak = 7 non-Race/Taper weeks
    # should carry strength.
    assert len(strength_weeks) >= 5, (
        f"Only {len(strength_weeks)} weeks have strength sessions; "
        f"VK auto-strength should populate every Base/Build/Peak/Recovery "
        f"week (Mujika & Padilla — strength pulled in Race + Taper weeks)."
    )


def test_vk_weekend_stack_keeps_climbing_session():
    """The canonical VK weekend stack is Saturday hill_repeats / vert_session
    + Sunday long_run on a mountain day. The regime-weekend cap (designed
    for road/ultra plans) used to trim Saturday's climb to ``easy`` because
    weekend_km_cap = 0.95 × 5 = 4.75 km. With the uphill_only bypass the
    Saturday hard workout survives in Build & Peak weeks."""
    weeks = _gen_vk()
    build_peak_weeks = [
        w for w in weeks if w['theme'].startswith(('Build', 'Peak'))
    ]
    sat_climb_weeks = 0
    for w in build_peak_weeks:
        sat = next((d for d in w['days'] if d['day'] == 'Saturday'), None)
        if sat and sat['workout_type'] in MOUNTAIN_WORKOUTS:
            sat_climb_weeks += 1
    # Allow last Peak week (dress rehearsal) to pin Saturday to easy_strides.
    # Out of 3 Build + 2 Peak = 5 candidate weeks, expect ≥ 3 to carry the
    # Sat-mountain stack.
    assert sat_climb_weeks >= 3, (
        f"Only {sat_climb_weeks}/{len(build_peak_weeks)} Build/Peak weeks "
        f"have a Saturday mountain workout — VK weekend specificity lost."
    )


def test_vk_build_uses_hill_repeats_not_tempo():
    """For all-uphill races, the Build catalog must swap flat ``tempo`` for
    ``hill_repeats`` (or its phase-appropriate downgrade ``intervals``).
    Flat tempo on a vertical-race plan trains the wrong metabolic system at
    the wrong muscular pattern."""
    weeks = _gen_vk()
    for w in weeks:
        if not w['theme'].startswith('Build'):
            continue
        types = [d['workout_type'] for d in w['days']]
        # Hill_repeats kept (mountain Sat) or downgraded to intervals when
        # the mountain budget pushes it off — but never raw flat tempo.
        assert 'tempo' not in types, (
            f"W{w['week_number']} (Build) contains flat tempo: {types} — "
            f"uphill_only races must replace tempo with hill_repeats."
        )


def test_vk_peak_carries_race_specific_climb():
    """Peak weeks must surface real vertical specificity — at least one
    high-vert session per Peak week (vert_session, hill_repeats, or a
    race_simulation rehearsal). Without this the Peak phase is just deload
    + flat tempos and the athlete arrives at the start line untested on
    real climbing pace."""
    weeks = _gen_vk()
    peak_weeks = [w for w in weeks if w['theme'].startswith('Peak')]
    assert peak_weeks, "no Peak weeks in plan"
    for w in peak_weeks:
        has_climb = any(
            d['elevation_m'] >= 500 and d['workout_type'] in (
                'vert_session', 'hill_repeats', 'race_simulation', 'long_run',
            )
            for d in w['days']
        )
        assert has_climb, (
            f"W{w['week_number']} (Peak) lacks any 500m+ vert session — "
            f"days={[(d['day'], d['workout_type'], d['elevation_m']) for d in w['days']]}"
        )


def test_vk_long_run_taper_deloads_from_real_peak():
    """Taper weeks deload from the achieved peak long-run, not from a
    spurious race × 0.75 target. With the fix, peak LR ~ 14 km in the last
    Peak week, so Taper-1 (≈ 50 %) should land around 7 km — not 2 km
    (which is what the unfixed code produced when peak_lr collapsed to
    race × 0.75 = 3.75 km)."""
    weeks = _gen_vk()
    taper_weeks = [w for w in weeks if w['theme'].startswith('Taper')]
    assert taper_weeks, "no Taper weeks in plan"
    # First Taper week's long_run should be ≥ 4 km (real deload from a real
    # peak); pre-fix it landed at ~ 2 km.
    first_taper = taper_weeks[0]
    lr = next(
        (d for d in first_taper['days'] if d['workout_type'] == 'long_run'),
        None,
    )
    assert lr is not None, "no long_run in first Taper week"
    assert lr['distance_km'] >= 4.0, (
        f"Taper-1 long_run = {lr['distance_km']} km — deload from a "
        f"collapsed peak; expected ≥ 4 km after VK long-run fix."
    )


def test_vk_taper2_long_run_above_floor():
    """Taper-2 (race week minus one) long_run must NOT collapse to a
    near-zero distance. Coach-review #45: a pathological combination of
    target_lr / peak_lr propagation could drop the Taper-2 long-run to
    1.4 km on a VK plan whose Peak peaked at 14 km. Bosquet et al. 2007
    Taper meta-analysis: Taper-2 sits at 30-40 % of peak typically;
    25 % is the floor below which the primary specificity stimulus is
    lost. The fix anchors a defensive floor at 25 % of peak_lr_so_far.
    """
    weeks = _gen_vk()
    taper_weeks = [w for w in weeks if w['theme'].startswith('Taper')]
    if len(taper_weeks) < 2:
        pytest.skip("plan only has 1 Taper week")
    second_taper = taper_weeks[-1]
    lr = next(
        (d for d in second_taper['days'] if d['workout_type'] == 'long_run'),
        None,
    )
    assert lr is not None, "no long_run in Taper-2 week"
    # Peak LR for this VK config ~ 14 km; 25 % floor = 3.5 km.
    assert lr['distance_km'] >= 3.5, (
        f"Taper-2 long_run = {lr['distance_km']} km — collapsed below the "
        f"25 % of peak floor (~3.5 km). Coach-review #45 regression."
    )


def test_vk_strength_title_is_phase_specific():
    """VK strength sessions must surface phase-specific routine snippets
    (squats, step-ups, calf raises etc.) rather than the generic
    "Strength & conditioning" placeholder. Vert.run / Suunto / Lavedrine
    2024 prescribe specific routines; the generic title is a coaching
    liability — coach-review #47.
    """
    weeks = _gen_vk()
    strength_titles = [
        d['title'] for w in weeks for d in w['days']
        if d['workout_type'] == 'strength'
    ]
    assert strength_titles, "no strength sessions in VK plan"
    for title in strength_titles:
        assert title != 'Strength & conditioning', (
            f"VK strength title '{title}' is the generic placeholder — "
            f"must surface a phase-specific routine."
        )
        # Sanity: must mention at least one canonical VK exercise.
        assert any(kw in title.lower() for kw in ('squat', 'step', 'bound')), (
            f"VK strength title '{title}' does not mention a canonical "
            f"VK exercise (squats / step-ups / step-downs / bounding)."
        )


def test_vk_taper_easy_pickups_respects_upper_cap():
    """Late-Taper easy_pickups must NOT balloon to a normal endurance
    run. Coach-review #46: ``_size_distances`` was allocating leftover
    Taper budget into a single 14 km easy_pickups day on a VK plan whose
    pickups range is (8, 10) — a 14 km "pickups" workout violates the
    Magness / Hudson / Pfitzinger taper protocol (pickups = 6-10 km easy
    + strides). The fix enforces a strict upper km cap for shakeout-by-
    design workouts (no 30 % allocation headroom).
    """
    weeks = _gen_vk()
    taper_weeks = [w for w in weeks if w['theme'].startswith('Taper')]
    for w in taper_weeks:
        for d in w['days']:
            if d['workout_type'] == 'easy_pickups':
                assert d['distance_km'] <= 10.0, (
                    f"W{w['week_number']} ({w['theme']}) easy_pickups = "
                    f"{d['distance_km']} km exceeds the 10 km strict upper "
                    f"cap — coach-review #46 regression."
                )


def test_vk_build_midweek_downgrade_preserves_climbing(_=None):
    """Coach-review #43. When the mountain budget pushes one Build hill_repeats
    off Saturday onto a midweek slot, the downgrade must NOT collapse to a
    flat ``intervals`` session sized at 0 m D+. The race-type-aware
    downgrade routes ``hill_repeats`` -> ``uphill_intervals`` for VK plans,
    preserving climbing density (~30-35 m/km) on rolling terrain.

    Vert.run / Suunto / Lavedrine 2024 explicitly: when threshold has to
    land midweek for a vertical race, do it on uphill terrain — flat
    threshold trains the wrong recruitment pattern.
    """
    weeks = _gen_vk()
    build_weeks = [w for w in weeks if w['theme'].startswith('Build')]
    assert build_weeks, "no Build weeks generated"
    saw_uphill_intervals = False
    for w in build_weeks:
        for d in w['days']:
            wt = d['workout_type']
            # Plain flat ``intervals`` (Build phase ⇒ flat per
            # FLAT_INTENSITY_PHASES_INTERVALS) must not appear.
            assert wt != 'intervals', (
                f"W{w['week_number']} (Build) ships flat ``intervals`` on "
                f"{d['day']} — uphill_only must downgrade to "
                f"``uphill_intervals`` instead. days="
                f"{[(x['day'], x['workout_type'], x['elevation_m']) for x in w['days']]}"
            )
            if wt == 'uphill_intervals':
                saw_uphill_intervals = True
                # The whole point: must carry real climbing density.
                km = d['distance_km']
                elev = d['elevation_m']
                density = elev / km if km > 0 else 0.0
                assert density >= 25.0, (
                    f"W{w['week_number']} (Build) {d['day']} uphill_intervals "
                    f"density={density:.0f} m/km is too low — workout has lost"
                    f" climbing specificity."
                )
                assert 'uphill' in d['title'].lower() or 'climb' in d['title'].lower(), (
                    f"uphill_intervals title='{d['title']}' must mention "
                    f"uphill / climbing — coach-review #43."
                )
    # The reproducer in #43 has only Sat as a mountain training day (Sun is
    # pinned long_run), so at least one Build week must downgrade onto
    # ``uphill_intervals``.
    assert saw_uphill_intervals, (
        "no Build week downgraded onto ``uphill_intervals`` — VK reproducer "
        "expects the second hill_repeats slot to land midweek as uphill_intervals."
    )


def test_vk_last_peak_dress_rehearsal_keeps_climbing_session():
    """Coach-review #44. The last Peak week (dress-rehearsal week) used to
    collapse the only midweek hard onto a 12 km / 0 m flat tempo. Mujika &
    Padilla 2003 + Magness: the pre-rehearsal midweek hard must match race
    specificity — for VK that means uphill, not flat threshold.

    With race-type-aware downgrade + the updated last-Peak hard collapse
    priority (``uphill_intervals`` ranks above ``tempo`` and ``intervals``),
    the surviving hard is a short uphill threshold — preserving climbing
    specificity 4-5 days before race day.
    """
    weeks = _gen_vk()
    peak_weeks = [w for w in weeks if w['theme'].startswith('Peak')]
    assert peak_weeks, "no Peak weeks in plan"
    last_peak = peak_weeks[-1]
    midweek_types = [
        (d['day'], d['workout_type'], d['elevation_m'])
        for d in last_peak['days']
        if d['day'] in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
    ]
    # Tempo is the bug — must not appear in the dress-rehearsal week for VK.
    assert all(wt != 'tempo' for _d, wt, _e in midweek_types), (
        f"VK last Peak week ships flat tempo midweek: {midweek_types} — "
        f"coach-review #44 regression."
    )
    # And the dress rehearsal should still keep one climbing session
    # (uphill_intervals or hill_repeats), not collapse to all-easy.
    hard_climbing = [
        wt for _d, wt, _e in midweek_types
        if wt in ('uphill_intervals', 'hill_repeats', 'vert_session')
    ]
    assert hard_climbing, (
        f"VK last Peak week has no climbing-specific midweek hard: "
        f"{midweek_types} — dress-rehearsal week needs at least one short"
        f" uphill session for race specificity."
    )


def test_vk_does_not_break_loop_race_long_run_cap():
    """Sanity: the uphill_only branch must not affect the standard
    ``loop`` race type. A 50 km / 3500 m loop ultra should still respect
    the LONG_RUN_MAX_FRACTION cap (LR ≤ 80 % × race_distance = 40 km)."""
    weeks = generate_plan(
        total_weeks=12, race_distance_km=50, race_elevation_m=3500,
        race_date='2026-08-01',
        athlete_weekly_km=55, athlete_weekly_elev=2100,
        athlete_longest_run_km=25, athlete_category='cat_2',
        long_run_day='Sunday', rest_days=['Friday'],
        race_type='loop',
        prefs={'max_weekly_km': 80, 'terrain_profile': 'mountain'},
    )
    for w in weeks:
        for d in w['days']:
            if d['workout_type'] == 'long_run':
                assert d['distance_km'] <= 50 * 0.80 + 0.5, (
                    f"loop race long_run {d['distance_km']} km exceeds "
                    f"LONG_RUN_MAX_FRACTION cap (40 km)."
                )

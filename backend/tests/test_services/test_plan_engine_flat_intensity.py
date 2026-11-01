"""Flat-intensity invariants for tempo and intervals.

Coaching consensus (Vert.run, Jason Koop, iRunFar): tempo runs and
Build/Base intervals belong on flat or rolling terrain — uphill versions
of these workouts are strength work, not threshold/VO2max stimulus.
Hill_repeats and vert_session continue to carry the uphill load.

Peak intervals are the deliberate exception: they remain uphill for
race-specificity (e.g. UTMB-style power climbs).
"""
import pytest

from services import plan_engine
from services.plan_engine import (
    FLAT_INTENSITY_DENSITY_CAP,
    _is_flat_intensity,
    _is_flat_prescription,
)


def _gen(prefs=None, *, total_weeks=14, race_distance_km=80,
         race_elevation_m=4000, athlete_weekly_km=70,
         athlete_longest_run_km=30, long_run_day='Saturday'):
    if prefs is None:
        prefs = {'max_weekly_km': 100, 'terrain_profile': 'mountain',
                 'mountain_days': ['Saturday', 'Sunday']}
    return plan_engine.generate_plan(
        total_weeks=total_weeks,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_date='2026-08-30',
        athlete_weekly_km=athlete_weekly_km,
        athlete_weekly_elev=2000,
        athlete_longest_run_km=athlete_longest_run_km,
        athlete_category='cat_2',
        long_run_day=long_run_day,
        rest_days=['Friday'],
        prefs=prefs,
    )


def _phase_of(week: dict) -> str:
    """Phase is encoded in the week ``theme`` (e.g. 'Peak — race-specific intensity').
    Returns the leading phase token ('Base', 'Build', 'Peak', 'Recovery',
    'Taper', 'Race') or '' if not parseable."""
    theme = week.get('theme') or ''
    if not theme:
        return ''
    head = theme.split('—', 1)[0].strip()
    return head.split()[0] if head else ''


def _days(weeks, workout_type, phase=None):
    out = []
    for w in weeks:
        if phase is not None and _phase_of(w) != phase:
            continue
        for d in w['days']:
            if d['workout_type'] == workout_type:
                out.append(d)
    return out


# ---------------------------------------------------------------------------
# _is_flat_intensity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('phase', ['Base', 'Build', 'Peak', 'Recovery', 'Taper', 'Race'])
def test_tempo_is_always_flat_intensity(phase):
    assert _is_flat_intensity('tempo', phase) is True


@pytest.mark.parametrize('phase', ['Base', 'Build'])
def test_intervals_flat_in_base_and_build(phase):
    assert _is_flat_intensity('intervals', phase) is True


def test_intervals_uphill_in_peak():
    assert _is_flat_intensity('intervals', 'Peak') is False


@pytest.mark.parametrize('wt', ['hill_repeats', 'vert_session', 'easy',
                                 'recovery', 'long_run', 'rest'])
def test_other_workouts_never_flat_intensity(wt):
    for phase in ('Base', 'Build', 'Peak'):
        assert _is_flat_intensity(wt, phase) is False


# ---------------------------------------------------------------------------
# End-to-end: generated plan respects flat-intensity caps
# ---------------------------------------------------------------------------

def test_tempo_density_at_or_below_flat_cap():
    """Every emitted tempo session must have D+/km <= FLAT_INTENSITY_DENSITY_CAP
    (or be snapped to 0 by redistribution)."""
    weeks = _gen()
    tempos = _days(weeks, 'tempo')
    assert tempos, "expected the engine to emit tempo sessions"
    for d in tempos:
        km = d['distance_km']
        elev = d['elevation_m']
        if km <= 0:
            continue
        if elev == 0:
            continue  # snapped to flat by redistribution — acceptable
        assert elev / km <= FLAT_INTENSITY_DENSITY_CAP + 0.01, (
            f"tempo too steep: {elev}m / {km}km = {elev/km:.1f} m/km"
        )


def test_build_intervals_density_at_or_below_flat_cap():
    """Build/Base intervals must be flat. Peak intervals are exempt
    (race-specific uphill)."""
    weeks = _gen()
    for w in weeks:
        if _phase_of(w) == 'Peak':
            continue
        for d in w['days']:
            if d['workout_type'] != 'intervals':
                continue
            km, elev = d['distance_km'], d['elevation_m']
            if km <= 0 or elev == 0:
                continue
            assert elev / km <= FLAT_INTENSITY_DENSITY_CAP + 0.01, (
                f"non-Peak intervals too steep: {elev}m / {km}km "
                f"in phase {_phase_of(w)}"
            )


def test_peak_intervals_remain_uphill_when_emitted():
    """Peak intervals are intentionally uphill for race-specificity.

    This invariant holds when the runner has mountain access on the
    interval day (i.e. ``mountain_days`` is unrestricted, or the placer
    puts intervals on a mountain-eligible day). The narrower "mountain
    only on weekends" case is a pre-existing limitation of the placer:
    if intervals land on a non-mountain weekday, FLAT_CITY_ELEV_DENSITY
    applies — independent of this option-1.5 change.
    """
    weeks = _gen(prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain'})
    peak_intervals = _days(weeks, 'intervals', phase='Peak')
    if not peak_intervals:
        pytest.skip("no Peak intervals emitted in this configuration")
    # At least one Peak intervals session should carry meaningful elevation
    # (not snapped to flat). Density should sit above the flat-intensity cap.
    significant = [d for d in peak_intervals
                   if d['distance_km'] > 0 and d['elevation_m'] > 0
                   and d['elevation_m'] / d['distance_km']
                   > FLAT_INTENSITY_DENSITY_CAP + 0.01]
    assert significant, (
        "Peak intervals should keep an uphill prescription, but every "
        "session was flattened"
    )


def test_tempo_title_advertises_flat():
    weeks = _gen()
    tempos = _days(weeks, 'tempo')
    assert tempos
    for d in tempos:
        assert 'flat' in d['title'].lower() or 'rolling' in d['title'].lower(), (
            f"tempo title should advertise flat/rolling terrain: {d['title']!r}"
        )


def test_build_intervals_title_advertises_flat():
    weeks = _gen()
    for w in weeks:
        if _phase_of(w) == 'Peak':
            continue
        for d in w['days']:
            if d['workout_type'] != 'intervals':
                continue
            t = d['title'].lower()
            assert 'flat' in t or 'rolling' in t, (
                f"non-Peak intervals title should advertise flat/rolling: "
                f"{d['title']!r} (phase {_phase_of(w)})"
            )


def test_peak_intervals_title_advertises_uphill():
    """When mountain access is broad enough that Peak intervals can land
    on a mountain day, the title must advertise the uphill prescription.
    Narrow-mountain plans are covered by ``test_peak_intervals_on_flat_day_get_flat_title``."""
    weeks = _gen(prefs={'max_weekly_km': 100, 'terrain_profile': 'mountain'})
    peak_intervals = _days(weeks, 'intervals', phase='Peak')
    if not peak_intervals:
        pytest.skip("no Peak intervals emitted in this configuration")
    for d in peak_intervals:
        assert 'uphill' in d['title'].lower(), (
            f"Peak intervals title should advertise uphill: {d['title']!r}"
        )


# ---------------------------------------------------------------------------
# Total weekly D+ should not collapse — saved budget redistributes to climbs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Follow-up bug: Peak intervals on a non-mountain day must not advertise
# uphill while D+ rounds to 0. Two concerns:
#   1. _is_flat_prescription correctly classifies the corner case.
#   2. The placer prefers mountain days for Peak intervals when the
#      mountain_set has slack (e.g. Sat/Sun with anchors elsewhere).
#   3. When mountain access is too narrow (Sat=vert anchor, Sun=long_run
#      anchor), Peak intervals fall back to flat with a coherent title.
# ---------------------------------------------------------------------------

def test_is_flat_prescription_inherits_phase_rules():
    """Tempo and Build/Base intervals are always flat regardless of D+."""
    assert _is_flat_prescription('tempo', 'Build', 10, 200) is True
    assert _is_flat_prescription('intervals', 'Build', 10, 300) is True
    assert _is_flat_prescription('intervals', 'Base', 10, 100) is True


def test_is_flat_prescription_peak_intervals_density_aware():
    """Peak intervals are flat when actually flat, uphill otherwise."""
    # Significantly above the flat cap → uphill.
    assert _is_flat_prescription('intervals', 'Peak', 10, 300) is False
    # At or below the flat cap → flat (the placer dropped them on a flat day).
    assert _is_flat_prescription('intervals', 'Peak', 10, 80) is True
    assert _is_flat_prescription('intervals', 'Peak', 10, 0) is True
    # Zero distance is a degenerate case — treat as flat (no climb stimulus).
    assert _is_flat_prescription('intervals', 'Peak', 0, 0) is True


def test_is_flat_prescription_other_workouts_unaffected():
    """Hill_repeats / vert_session / easy / long_run never treated flat."""
    for wt in ('hill_repeats', 'vert_session', 'easy', 'recovery', 'long_run'):
        assert _is_flat_prescription(wt, 'Peak', 10, 0) is False
        assert _is_flat_prescription(wt, 'Build', 10, 500) is False


def test_peak_intervals_on_flat_day_get_flat_title():
    """Regression: with mountain_days = [Sat, Sun] both anchors occupy the
    weekend (vert_session + long_run), so Peak intervals can only land on
    a weekday. The title must say flat/rolling, not "uphill"."""
    weeks = _gen()  # default: mountain_days=[Saturday, Sunday]
    peak_intervals = _days(weeks, 'intervals', phase='Peak')
    if not peak_intervals:
        pytest.skip("no Peak intervals emitted in this configuration")
    for d in peak_intervals:
        km, elev = d['distance_km'], d['elevation_m']
        if km > 0 and elev / km > FLAT_INTENSITY_DENSITY_CAP:
            # This one ended up on a mountain day — uphill title is correct.
            assert 'uphill' in d['title'].lower()
        else:
            # Flat-prescribed → must NOT advertise uphill.
            t = d['title'].lower()
            assert 'uphill' not in t, (
                f"Peak intervals on flat day still says 'uphill': {d['title']!r}"
            )
            assert 'flat' in t or 'rolling' in t, (
                f"Peak intervals on flat day should advertise flat/rolling: "
                f"{d['title']!r}"
            )


def test_peak_intervals_on_flat_day_redistribute_budget():
    """The 50m sized for Peak intervals on a flat day shouldn't be wasted —
    redistribution must move it to vert_session / race_simulation /
    hill_repeats. Verify the week's actual D+ is close to its planned
    pre-redistribution total."""
    weeks = _gen()  # weekend-only mountain
    peak_weeks = [w for w in weeks if _phase_of(w) == 'Peak']
    assert peak_weeks, "expected at least one Peak week"
    for w in peak_weeks:
        actual = w.get('total_elevation_m') or 0
        planned = (w.get('_meta') or {}).get('elev_planned_total_m') or 0
        if planned <= 0:
            continue
        assert actual >= 0.85 * planned, (
            f"Peak week {w['week_number']} D+ leaked: actual={actual} "
            f"vs planned={planned}"
        )


def test_placer_prefers_mountain_for_peak_intervals_when_slack_exists():
    """When mountain_days includes a weekday and the anchor sessions don't
    consume every mountain slot, the placer should put Peak intervals on
    a mountain day so the prescription stays uphill (race-specific).

    Uses long_run_day='Sunday' so the post-LR penalty (which avoids hard
    sessions the day after the long run) doesn't conflict with placing
    intervals on the Saturday mountain day. Race elevation is kept below
    DESCENT_TRAINING_ELEV_THRESHOLD so descent_session isn't injected and
    competing for the weekday mountain slot.
    """
    prefs = {
        'max_weekly_km': 100,
        'terrain_profile': 'mountain',
        # Wednesday is mountain-eligible AND not occupied by long_run/vert anchor.
        'mountain_days': ['Wednesday', 'Saturday', 'Sunday'],
    }
    weeks = _gen(prefs=prefs, race_elevation_m=1200, long_run_day='Sunday')
    peak_intervals = _days(weeks, 'intervals', phase='Peak')
    if not peak_intervals:
        pytest.skip("no Peak intervals emitted")
    # At least one Peak intervals session should land on a mountain day,
    # carrying meaningful uphill density (above the flat cap).
    on_mountain = [
        d for d in peak_intervals
        if d['day'] in prefs['mountain_days']
        and d['distance_km'] > 0
        and d['elevation_m'] / d['distance_km'] > FLAT_INTENSITY_DENSITY_CAP
    ]
    assert on_mountain, (
        "Peak intervals should be placed on a mountain day when one is "
        "available; got: " + str([(d['day'], d['elevation_m']) for d in peak_intervals])
    )


def test_weekly_elevation_budget_preserved_via_redistribution():
    """Flattening tempo/intervals should not shrink the total weekly D+ —
    the saved budget is poured onto hill_repeats / vert_session / race_sim
    by ``_redistribute_elevation``. Compares the final week total to the
    pre-redistribution planned total recorded in ``_meta``."""
    weeks = _gen()
    build_weeks = [w for w in weeks if _phase_of(w) == 'Build']
    assert build_weeks, "expected at least one Build week"
    for w in build_weeks:
        actual_elev = w.get('total_elevation_m') or 0
        meta = w.get('_meta') or {}
        planned_total = meta.get('elev_planned_total_m') or 0
        if planned_total <= 0:
            continue
        # Redistribution should preserve at least 80% of the planned D+.
        # Some loss is expected when sinks hit the per-day density cap and
        # residual budget can't be placed.
        assert actual_elev >= 0.80 * planned_total, (
            f"Build week {w['week_number']} D+ collapsed: actual={actual_elev}m "
            f"vs planned={planned_total}m"
        )

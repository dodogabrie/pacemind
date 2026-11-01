"""Tests for `services/activity_ingest/streams.py`.

Two layers:

1. Contract/maths checks on synthetic geometry — always run. These pin the
   *shape* of the output (units, which keys are omitted) and the correctness of
   the centred-difference maths. They say nothing about distribution drift.

2. The distribution-drift guard — skipped until a ground-truth fixture pair is
   checked into `backend/tests/fixtures/stream_calibration/`. This is the test
   the plan asks for: it enforces |Δv_flat| < 2% and |Δpredicted time| < 1.5%
   between Strava's own smoothing and ours, so a future refactor of the
   smoothing window cannot silently push the residual GBM out of distribution.

   See `backend/scripts/calibrate_streams.py` for exactly which files to drop
   in and how to export them.
"""

import math

import pytest

from scripts.calibrate_streams import (
    PREDICTED_TIME_TOLERANCE_PCT,
    V_FLAT_TOLERANCE_PCT,
    compare_pair,
    find_fixture_pairs,
    load_reference_route,
)
from services.activity_ingest.streams import (
    GRADE_SMOOTHING_DISTANCE_M,
    MOVING_SPEED_THRESHOLD_MS,
    derive_streams,
)

# 1 degree of latitude ~= 111.19 km; enough for a synthetic track with known
# geometry without pulling in a projection library.
_M_PER_DEG_LAT = 111194.9

_NO_FIXTURES = (
    'No ground-truth fixture pair in backend/tests/fixtures/stream_calibration/. '
    'The derive_streams() calibration number does NOT exist yet — this tolerance '
    'is unverified until a <name>.strava.json + <name>.gpx pair is checked in. '
    'See backend/scripts/calibrate_streams.py for the export instructions.'
)


def _straight_track(n=200, spacing_m=10.0, grade=0.05, speed_ms=3.0):
    """A due-north track at constant grade and constant speed."""
    lat = [45.0 + i * spacing_m / _M_PER_DEG_LAT for i in range(n)]
    lon = [7.0] * n
    ele = [1000.0 + grade * i * spacing_m for i in range(n)]
    time = [i * spacing_m / speed_ms for i in range(n)]
    return lat, lon, ele, time


# ---------------------------------------------------------------------------
# 1. Contract + maths
# ---------------------------------------------------------------------------

def test_constant_grade_and_speed_recovered():
    """A constant 5% / 3 m/s track must come back as 5.0 and 3.0."""
    lat, lon, ele, time = _straight_track(grade=0.05, speed_ms=3.0)
    s = derive_streams(lat, lon, ele, time)

    # grade_smooth is percent (Strava's unit), not a fraction.
    assert all(math.isclose(g, 5.0, abs_tol=0.05) for g in s['grade_smooth'])
    assert all(math.isclose(v, 3.0, rel_tol=0.02) for v in s['velocity_smooth'])
    assert all(s['moving'])
    # Haversine distance must match the geometry we laid down (10 m spacing).
    assert math.isclose(s['distance'][-1], 10.0 * 199, rel_tol=0.005)


def test_grade_window_is_the_only_smoothing_knob():
    """A single-point elevation spike is attenuated by the window width."""
    lat, lon, ele, time = _straight_track(grade=0.0)
    ele = list(ele)
    ele[100] += 5.0  # 5 m spike on one sample

    s = derive_streams(lat, lon, ele, time)
    peak = max(abs(g) for g in s['grade_smooth'])
    # Centred difference over the window: the spike contributes at most
    # 5 m / window, in percent. Anything larger means the window is not
    # actually being applied.
    assert peak <= 100.0 * 5.0 / GRADE_SMOOTHING_DISTANCE_M + 1e-6


def test_missing_inputs_are_omitted_not_zero_filled():
    """Consumers check key presence — a zero-filled stream reads as real data."""
    lat, lon, ele, time = _straight_track()

    no_time = derive_streams(lat, lon, ele)
    assert 'grade_smooth' in no_time and 'altitude' in no_time
    for key in ('time', 'velocity_smooth', 'moving'):
        assert key not in no_time

    no_ele = derive_streams(lat, lon, None, time)
    assert 'velocity_smooth' in no_ele
    for key in ('altitude', 'grade_smooth'):
        assert key not in no_ele

    # Sensor channels are pass-through and absent unless supplied.
    for key in ('heartrate', 'cadence', 'watts'):
        assert key not in no_time
    assert derive_streams(lat, lon, ele, time, heartrate=[140] * len(lat))['heartrate'][0] == 140


def test_stopped_points_are_not_moving():
    lat, lon, ele, time = _straight_track(n=100, spacing_m=10.0, speed_ms=3.0)
    # Freeze in place for 60 s in the middle: same position, advancing clock.
    lat = lat[:50] + [lat[49]] * 60 + lat[50:]
    lon = lon[:50] + [lon[49]] * 60 + lon[50:]
    ele = ele[:50] + [ele[49]] * 60 + ele[50:]
    time = time[:50] + [time[49] + 1 + i for i in range(60)] + [t + 61 for t in time[50:]]

    s = derive_streams(lat, lon, ele, time)
    assert not all(s['moving'])
    assert min(s['velocity_smooth']) < MOVING_SPEED_THRESHOLD_MS
    assert all(v >= 0 for v in s['velocity_smooth'])


def test_elevation_gaps_are_interpolated():
    lat, lon, ele, time = _straight_track(grade=0.05)
    ele = list(ele)
    ele[50] = None
    s = derive_streams(lat, lon, ele, time)
    assert all(math.isclose(g, 5.0, abs_tol=0.05) for g in s['grade_smooth'])


def test_degenerate_inputs():
    assert derive_streams([45.0], [7.0], [100.0], [0.0]) == {}
    assert derive_streams([], []) == {}
    with pytest.raises(ValueError):
        derive_streams([45.0, 45.1], [7.0])
    with pytest.raises(ValueError):
        derive_streams([45.0, None], [7.0, 7.1])


# ---------------------------------------------------------------------------
# 2. Distribution-drift guard (needs ground truth)
# ---------------------------------------------------------------------------

_PAIRS = find_fixture_pairs()


@pytest.mark.skipif(not _PAIRS, reason=_NO_FIXTURES)
@pytest.mark.parametrize('pair', _PAIRS, ids=[p['name'] for p in _PAIRS])
def test_derived_streams_match_strava_within_tolerance(pair):
    """Our smoothing must not move v_flat or predicted time off Strava's."""
    report = compare_pair(pair['strava'], pair['gpx'], load_reference_route())

    v_delta = report['v_flat_delta_pct']
    assert v_delta is not None, 'v_flat could not be computed from the fixture'
    assert abs(v_delta) <= V_FLAT_TOLERANCE_PCT, (
        f"v_flat drift {v_delta:+.2f}% exceeds ±{V_FLAT_TOLERANCE_PCT}% "
        f"(strava {report['v_flat_strava']:.3f} vs derived "
        f"{report['v_flat_derived']:.3f} m/s). Retune "
        f"GRADE_SMOOTHING_DISTANCE_M / VELOCITY_SMOOTHING_TIME_S with "
        f"scripts/calibrate_streams.py."
    )

    t_delta = report['predicted_time_delta_pct']
    assert t_delta is not None, 'predicted time could not be computed'
    assert abs(t_delta) <= PREDICTED_TIME_TOLERANCE_PCT, (
        f"predicted-time drift {t_delta:+.2f}% exceeds "
        f"±{PREDICTED_TIME_TOLERANCE_PCT}% "
        f"({report['predicted_time_strava_s']:.0f}s vs "
        f"{report['predicted_time_derived_s']:.0f}s)."
    )

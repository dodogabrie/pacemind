"""Canonical stream derivation for non-Strava activity sources.

`derive_streams()` is the **only** place where `grade_smooth` and
`velocity_smooth` are computed for activities that did not come from Strava.
No normalizer may roll its own — see
`docs/plans/multi-source-activities/02-activity-abstraction.md`, section
"The distribution-drift risk".

Why that matters: Strava does not hand back raw data. Their `grade_smooth` and
`velocity_smooth` are the output of *their* smoothing, and the Tier 2 calibration
(`services/physics_model/calibration.py`) is fitted on that distribution. Derive
grade over a different window and the fit silently goes out of distribution:
predictions degrade and nothing raises. The two window constants below are the
single tuning surface for that, and `scripts/calibrate_streams.py` is the
harness that measures them against ground truth.

Output keys are exactly Strava's (`services/strava_service.py:132`):

    time, distance, altitude, latlng, velocity_smooth,
    grade_smooth, moving, heartrate, cadence, watts

Keys that cannot be derived are **omitted, never zero-filled** — consumers
check for presence (`physics_prediction_service.py:31`,
`user_residual_service.py:64`, `performance_tracker.py:517`) and a zero-filled
stream reads as real data.
"""

from datetime import datetime
from typing import Dict, List, Optional, Sequence

import numpy as np

from services.data_processor import haversine

# ---------------------------------------------------------------------------
# Tuning surface — the whole point of scripts/calibrate_streams.py
# ---------------------------------------------------------------------------

# TODO(stream-drift #82 — see GH issues): both windows below are UNCALIBRATED.
# There is no ground-truth fixture in the repo (Strava streams + the matching
# original GPX for the same activity), so they were reasoned from Strava's
# ~1 Hz sampling rather than measured. Phase 2 of the multi-source epic must
# not ship until scripts/calibrate_streams.py has been run against real pairs
# and the measured deltas written into the plan document.
GRADE_SMOOTHING_DISTANCE_M = 30.0
"""Span of the centred finite difference used for `grade_smooth`, in metres.

Grade at a point is (ele(d + h/2) - ele(d - h/2)) / h — the window *is* the
smoothing, so there is exactly one knob rather than a filter plus a
differentiator. 30 m is the starting guess, not a measured value: Strava
samples at ~1 Hz and a runner covers ~3 m/s, so their ~10 s smoothing spans
roughly 30 m. Retune from the calibration harness once fixtures exist.
"""

VELOCITY_SMOOTHING_TIME_S = 10.0
"""Span of the centred finite difference used for `velocity_smooth`, seconds.

Same construction as grade, over time instead of distance. Paired with the
30 m grade window at typical running speed so the two agree about how much
terrain they average over.
"""

MOVING_SPEED_THRESHOLD_MS = 0.5
"""Speed below which a point counts as stopped.

Strava's `moving` flag comes from a proprietary algorithm; this is a plain
threshold that matches the lower velocity bound already used in
`physics_model/calibration.py:56`.
ponytail: naive threshold, no hysteresis or dwell time — a runner hovering
around the cut-off will flicker. Upgrade to a min-dwell debounce only if the
calibration harness shows stopped-time drift against Strava.
"""

# Guard against zero-length spans (stationary points, duplicate timestamps).
_MIN_SPAN = 1e-6


def derive_streams(
    lat: Sequence[float],
    lon: Sequence[float],
    ele: Optional[Sequence[Optional[float]]] = None,
    time: Optional[Sequence] = None,
    distance: Optional[Sequence[float]] = None,
    heartrate: Optional[Sequence] = None,
    cadence: Optional[Sequence] = None,
    watts: Optional[Sequence] = None,
) -> Dict[str, List]:
    """Build canonical activity streams from raw track points.

    Args:
        lat: Latitudes, degrees. Required.
        lon: Longitudes, degrees. Required, same length as `lat`.
        ele: Elevations in metres. May contain None (gap-filled by linear
            interpolation). Omit or pass all-None to skip `altitude` and
            `grade_smooth`.
        time: Point timestamps — `datetime`, ISO-8601 strings, or numeric
            seconds. May contain None. Omit to skip `time`,
            `velocity_smooth` and `moving` (e.g. a route GPX with no track
            times).
        distance: Cumulative distance in metres, if the source records it
            (FIT files do, and their sensor-derived distance beats
            recomputing from GPS). Derived by haversine when absent.
        heartrate: Pass-through sensor channel, emitted verbatim.
        cadence: Pass-through sensor channel, emitted verbatim.
        watts: Pass-through sensor channel, emitted verbatim.

    Returns:
        Dict of canonical stream keys to plain lists, missing keys omitted.
        Empty dict if there are fewer than 2 points.

    Raises:
        ValueError: If `lat`/`lon` differ in length, contain None, or if a
            pass-through channel has a different length.
    """
    lat = _as_float_array(lat, 'lat')
    lon = _as_float_array(lon, 'lon')
    n = len(lat)
    if len(lon) != n:
        raise ValueError(f'lat/lon length mismatch: {n} vs {len(lon)}')
    if n < 2:
        # One point has no gradient and no speed; nothing meaningful to emit.
        return {}
    if np.isnan(lat).any() or np.isnan(lon).any():
        raise ValueError('lat/lon must not contain None/NaN')

    streams: Dict[str, List] = {
        'latlng': [[float(a), float(o)] for a, o in zip(lat, lon)],
    }

    dist = _cumulative_distance(lat, lon) if distance is None else _as_float_array(distance, 'distance')
    if len(dist) != n:
        raise ValueError(f'distance length mismatch: {len(dist)} vs {n}')
    # A supplied distance stream must be monotonic for the interpolations below.
    dist = np.maximum.accumulate(np.nan_to_num(dist, nan=0.0))
    streams['distance'] = dist.tolist()

    altitude = _fill_gaps(ele, n) if ele is not None else None
    if altitude is not None:
        streams['altitude'] = altitude.tolist()
        # Percent, matching Strava — consumers divide by 100
        # (physics_model/calibration.py:64).
        streams['grade_smooth'] = (100.0 * _centred_slope(
            dist, altitude, dist, GRADE_SMOOTHING_DISTANCE_M
        )).tolist()

    elapsed = _elapsed_seconds(time, n) if time is not None else None
    if elapsed is not None:
        streams['time'] = [int(round(t)) for t in elapsed]
        velocity = _centred_slope(
            elapsed, dist, elapsed, VELOCITY_SMOOTHING_TIME_S
        )
        velocity = np.clip(velocity, 0.0, None)
        streams['velocity_smooth'] = velocity.tolist()
        streams['moving'] = (velocity > MOVING_SPEED_THRESHOLD_MS).tolist()

    for key, values in (('heartrate', heartrate), ('cadence', cadence), ('watts', watts)):
        if values is None:
            continue
        values = list(values)
        if len(values) != n:
            raise ValueError(f'{key} length mismatch: {len(values)} vs {n}')
        streams[key] = values

    return streams


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _centred_slope(
    x: np.ndarray,
    y: np.ndarray,
    at: np.ndarray,
    span: float,
) -> np.ndarray:
    """Slope dy/dx evaluated over a centred window of width `span`.

    The finite difference over a wide window *is* the smoothing: one window
    constant instead of a filter plus a differentiator, and no phase shift.
    Near the ends the window is clipped to the available range and the slope
    divided by the real span, so edges are noisier but not biased toward zero
    the way constant extrapolation would make them.
    """
    lo = np.clip(at - span / 2.0, x[0], x[-1])
    hi = np.clip(at + span / 2.0, x[0], x[-1])
    actual_span = np.maximum(hi - lo, _MIN_SPAN)
    return (np.interp(hi, x, y) - np.interp(lo, x, y)) / actual_span


def _cumulative_distance(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Cumulative haversine distance in metres, starting at 0."""
    # ponytail: scalar haversine in a loop, reusing the existing helper. ~20ms
    # for a 10k-point activity, which is noise next to the HTTP/DB work around
    # it. Vectorise only if bulk imports show up in a profile.
    steps = [0.0]
    for i in range(1, len(lat)):
        steps.append(haversine(lat[i - 1], lon[i - 1], lat[i], lon[i]))
    return np.cumsum(steps)


def _as_float_array(values: Sequence, name: str) -> np.ndarray:
    try:
        return np.asarray([np.nan if v is None else float(v) for v in values], dtype=float)
    except (TypeError, ValueError) as e:
        raise ValueError(f'{name} must be numeric: {e}') from e


def _fill_gaps(values: Sequence[Optional[float]], n: int) -> Optional[np.ndarray]:
    """Linearly interpolate None/NaN holes; return None if nothing is usable."""
    arr = _as_float_array(values, 'ele')
    if len(arr) != n:
        raise ValueError(f'ele length mismatch: {len(arr)} vs {n}')
    good = ~np.isnan(arr)
    if not good.any():
        return None
    if good.all():
        return arr
    idx = np.arange(n)
    return np.interp(idx, idx[good], arr[good])


def _elapsed_seconds(times: Sequence, n: int) -> Optional[np.ndarray]:
    """Convert timestamps to seconds since the first point.

    Accepts datetimes, ISO-8601 strings, or numbers already in seconds.
    Returns None if fewer than two timestamps are usable, or if time does not
    advance (some devices emit a constant timestamp).
    """
    if len(times) != n:
        raise ValueError(f'time length mismatch: {len(times)} vs {n}')

    seconds: List[float] = []
    for value in times:
        seconds.append(np.nan if value is None else _to_epoch_seconds(value))
    arr = np.asarray(seconds, dtype=float)

    good = ~np.isnan(arr)
    if good.sum() < 2:
        return None
    if not good.all():
        idx = np.arange(n)
        arr = np.interp(idx, idx[good], arr[good])

    arr = arr - arr[0]
    if arr[-1] <= 0:
        return None
    # Timestamps must not go backwards for np.interp in _centred_slope.
    return np.maximum.accumulate(arr)


def _to_epoch_seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        # fromisoformat handles the 'Z' suffix from Python 3.11 onward; this
        # project is on 3.12.
        return datetime.fromisoformat(value).timestamp()
    raise ValueError(f'unsupported timestamp type: {type(value).__name__}')

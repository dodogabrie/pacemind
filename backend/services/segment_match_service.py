"""Same-stretch matching across runs + improvement index (pure functions).

A stretch is a start and an end point taken from one run's latlng stream. A
past run "passes" it when it comes within ``tol_m`` of the start and, later,
of the end, over a distance within ``LEN_TOL`` of the stretch length.
Efficiency = grade-adjusted metres per minute per heartbeat above rest, so a
slower day at a lower HR does not read as a regression.
"""

from typing import Dict, List, Optional

import numpy as np

from services import workout_analysis_service as wa

EARTH_R = 6371000.0
LEN_TOL = 0.15
MIN_PASSES = 3


def _dist_m(ll: np.ndarray, lat: float, lng: float) -> np.ndarray:
    """Equirectangular distance (m) from every [lat, lng] row to one point; fine below a few km."""
    x = np.radians(ll[:, 1] - lng) * np.cos(np.radians(lat))
    y = np.radians(ll[:, 0] - lat)
    return EARTH_R * np.hypot(x, y)


def has_latlng(streams: Optional[Dict]) -> bool:
    ll, d = (streams or {}).get('latlng'), (streams or {}).get('distance')
    return bool(ll and d and len(ll) == len(d))


def stretch(streams: Dict, start_m: float, end_m: float) -> Optional[Dict]:
    """Start/end points of [start_m, end_m] on this run, or None without GPS."""
    if not has_latlng(streams) or end_m <= start_m:
        return None
    d = np.asarray(streams['distance'], dtype=float)
    lo, hi = (int(min(np.searchsorted(d, x), len(d) - 1)) for x in (start_m, end_m))
    if hi <= lo:
        return None
    ll = streams['latlng']
    return {'start': list(ll[lo]), 'end': list(ll[hi]), 'length_m': float(d[hi] - d[lo]), 'lo': lo, 'hi': hi}


def find_pass(streams: Dict, st: Dict, tol_m: float = 30.0) -> Optional[tuple]:
    """(lo, hi) sample indexes of the first pass over ``st``, or None.

    ponytail: first pass only; a loop run repeated twice counts once.
    """
    if not has_latlng(streams):
        return None
    ll = np.asarray(streams['latlng'], dtype=float)
    d = np.asarray(streams['distance'], dtype=float)
    ds, de = _dist_m(ll, *st['start']), _dist_m(ll, *st['end'])
    near_s = np.nonzero(ds <= tol_m)[0]
    if not len(near_s):
        return None
    # each contiguous visit to the start point -> its closest sample
    for run in np.split(near_s, np.nonzero(np.diff(near_s) > 1)[0] + 1):
        lo = int(run[np.argmin(ds[run])])
        span = d - d[lo]
        ok = np.nonzero((de <= tol_m) & (span >= st['length_m'] * (1 - LEN_TOL))
                        & (span <= st['length_m'] * (1 + LEN_TOL)))[0]
        if len(ok):
            hi = int(ok[np.argmin(de[ok])])
            return lo, hi
    return None


def pass_metrics(streams: Dict, lo: int, hi: int, hr_rest: float) -> Optional[Dict]:
    t = np.asarray(streams['time'], dtype=float)
    dt = float(t[hi] - t[lo])
    if dt <= 0:
        return None
    usable = wa.altitude_usable(streams)
    gap_v = wa._flat_equiv_speed(streams, usable)
    gap_m = float(np.mean(gap_v[lo:hi + 1]) * dt) if gap_v is not None else None
    out = {'time_s': int(round(dt))}
    hr = streams.get('heartrate') or []
    if len(hr) == len(t):
        out['hr'] = int(round(float(np.mean(hr[lo:hi + 1]))))
        if gap_m and out['hr'] > hr_rest + 10:
            out['m_per_beat'] = round(gap_m / (dt / 60) / (out['hr'] - hr_rest), 3)
    alt = streams.get('altitude') or []
    if usable and len(alt) == len(t):
        out['vertical_m_h'] = round(abs(float(alt[hi]) - float(alt[lo])) / dt * 3600)
    return out


def improvement(today: Dict, past: List[Dict], metric: str = 'eff') -> Dict:
    """Today vs the median of past passes, in % (positive = better).

    metric 'eff': m_per_beat (higher is better); 'time': time_s (lower is better).
    Each past row gets its own index against the same median.
    """
    key = 'm_per_beat' if metric == 'eff' else 'time_s'
    vals = [p[key] for p in past if p.get(key)]
    if len(vals) < MIN_PASSES or not today.get(key):
        return {'index_pct': None, 'n_past': len(vals),
                'note': f'need at least {MIN_PASSES} past passes with {key}'}
    med = float(np.median(vals))
    pct = (lambda v: (v / med - 1) * 100) if metric == 'eff' else (lambda v: (med / v - 1) * 100)
    for p in past:
        p['index_pct'] = round(pct(p[key]), 1) if p.get(key) else None
    return {'index_pct': round(pct(today[key]), 1), 'n_past': len(vals), 'median': round(med, 3)}

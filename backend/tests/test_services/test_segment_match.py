"""Same-stretch matching and improvement index (synthetic GPS tracks)."""

import numpy as np

from services import segment_match_service as sm

M_PER_DEG = 111195.0


def _run(offset_m=0.0, v=3.0, hr=140, n=2000, reverse=False):
    """Straight line north at v m/s; the stretch of interest starts offset_m in."""
    t = np.arange(n, dtype=float)
    d = v * t
    lat = (d + offset_m) / M_PER_DEG
    if reverse:
        lat = lat[::-1]
    return {'time': t.tolist(), 'distance': d.tolist(), 'latlng': [[float(a), 0.0] for a in lat],
            'velocity_smooth': [v] * n, 'heartrate': [hr] * n,
            'altitude': [100.0] * n, 'grade_smooth': [0.0] * n}


def test_finds_same_stretch_and_direction():
    today = _run()
    st = sm.stretch(today, 1000, 3000)
    assert abs(st['length_m'] - 2000) < 5
    lo, hi = sm.find_pass(_run(offset_m=500), st)          # same road, started 500 m earlier
    past = _run(offset_m=500)
    assert abs(past['distance'][lo] - 500) < 5 and abs(past['distance'][hi] - 2500) < 5
    assert sm.find_pass(_run(reverse=True), st) is None     # wrong direction
    assert sm.find_pass(_run(offset_m=50000), st) is None   # somewhere else


def test_efficiency_and_index():
    rest = 60
    slow_low = sm.pass_metrics(_run(v=2.5, hr=120), 0, 800, rest)   # 2.5 m/s at 60 beats over rest
    fast_high = sm.pass_metrics(_run(v=3.0, hr=160), 0, 800, rest)  # 3.0 m/s at 100 over rest
    assert slow_low['m_per_beat'] > fast_high['m_per_beat']        # slower but more efficient
    past = [{'m_per_beat': 2.0, 'time_s': 600}, {'m_per_beat': 2.2, 'time_s': 580},
            {'m_per_beat': 2.4, 'time_s': 560}]
    r = sm.improvement({'m_per_beat': 2.42, 'time_s': 550}, past, 'eff')
    assert r['index_pct'] == 10.0 and r['n_past'] == 3
    assert sm.improvement({'time_s': 522}, past, 'time')['index_pct'] == 11.1
    assert sm.improvement({'m_per_beat': 2.0}, past[:2], 'eff')['index_pct'] is None

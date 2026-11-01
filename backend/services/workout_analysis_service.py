"""Single-workout analysis: pure functions over a Strava-style streams dict.

``streams`` keys (lists, equal length): time (s), distance (m), altitude (m),
grade_smooth (%), velocity_smooth (m/s), heartrate, cadence (rpm, one foot),
moving. Everything here returns small JSON-able dicts, never raw streams.
"""

import math
from typing import Dict, List, Optional

import numpy as np

from services.pace_zone_service import ZONE_ORDER
from services.physics_model.core import normalized_cost_ratio

TREADMILL_ALT_RANGE_M = 5.0      # altitude range below this over >1 km = flat/fake
CLIMB_MIN_GAIN_M = 20.0
CLIMB_MIN_GRADE_PCT = 3.0
CLIMB_HYSTERESIS_M = 10.0
MAX_ROWS = 60
MIN_WORK_S, MIN_BLOCKS = 30, 3


def _arr(streams: Dict, key: str) -> Optional[np.ndarray]:
    v = streams.get(key) or []
    return np.asarray(v, dtype=float) if len(v) else None


def has_streams(streams: Optional[Dict]) -> bool:
    return bool(streams and streams.get('time') and streams.get('distance'))


def altitude_usable(streams: Dict) -> bool:
    """False for treadmill / indoor runs: no altitude, or a flat line over real distance."""
    alt, dist = _arr(streams, 'altitude'), _arr(streams, 'distance')
    if alt is None or dist is None or len(alt) != len(dist):
        return False
    if dist[-1] < 1000:
        return True
    return float(np.ptp(alt)) >= TREADMILL_ALT_RANGE_M


def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) < w or w < 2:
        return x
    pad = np.pad(x, (w // 2, w - 1 - w // 2), mode='edge')
    return np.convolve(pad, np.ones(w) / w, mode='valid')


def _gain_loss(alt: np.ndarray) -> tuple:
    d = np.diff(_smooth(alt, 5))
    return float(d[d > 0].sum()), float(-d[d < 0].sum())


def _flat_equiv_speed(streams: Dict, usable_alt: bool) -> Optional[np.ndarray]:
    """Speed * Minetti cost ratio of the grade = grade-adjusted speed (m/s)."""
    v = _arr(streams, 'velocity_smooth')
    if v is None:
        return None
    g = _arr(streams, 'grade_smooth')
    if not usable_alt or g is None or len(g) != len(v):
        return v
    ratio = np.array([normalized_cost_ratio(max(-0.3, min(0.3, x / 100.0))) for x in g])
    return v * ratio


def _pace(speed: float) -> Optional[int]:
    return int(round(1000 / speed)) if speed and speed > 0.3 else None


def _row(streams, lo, hi, usable_alt, gap_v, label) -> Dict:
    """Metrics for samples lo..hi (inclusive indexes)."""
    t, d = _arr(streams, 'time'), _arr(streams, 'distance')
    dist = float(d[hi] - d[lo])
    dt = float(t[hi] - t[lo])
    row = {'label': label, 'distance_m': round(dist), 'time_s': int(round(dt)),
           'pace_s_km': _pace(dist / dt) if dt > 0 else None}
    if gap_v is not None and usable_alt:
        row['gap_s_km'] = _pace(float(np.mean(gap_v[lo:hi + 1])))
    for key, name in (('heartrate', 'hr'), ('cadence', 'cadence_spm')):
        a = _arr(streams, key)
        if a is not None and len(a) == len(t):
            m = float(np.mean(a[lo:hi + 1]))
            row[name] = int(round(m * (2 if key == 'cadence' else 1)))
    if usable_alt:
        alt = _arr(streams, 'altitude')[lo:hi + 1]
        up, down = _gain_loss(alt)
        row.update(d_plus=round(up), d_minus=round(down),
                   grade_pct=round(float(alt[-1] - alt[0]) / dist * 100, 1) if dist > 0 else None)
    return row


def splits(streams: Dict, step_m: float = 1000.0) -> List[Dict]:
    """Fixed-distance splits (last partial split kept when >= 30 % of step)."""
    d = _arr(streams, 'distance')
    usable = altitude_usable(streams)
    gap_v = _flat_equiv_speed(streams, usable)
    total = float(d[-1])
    step_m = max(step_m, total / MAX_ROWS)
    edges = list(np.arange(0, total, step_m)) + [total]
    if len(edges) > 2 and edges[-1] - edges[-2] < 0.3 * step_m:
        edges.pop(-2)
    idx = np.searchsorted(d, edges, side='left')
    rows = []
    for i in range(len(idx) - 1):
        lo, hi = int(idx[i]), min(int(idx[i + 1]), len(d) - 1)
        if hi > lo:
            rows.append(_row(streams, lo, hi, usable, gap_v, f'{edges[i] / 1000:.1f}km'))
    return rows


def hr_zone_times(streams: Dict, zones: Optional[Dict]) -> Optional[Dict]:
    """Seconds and % of time per HR zone. ``zones``: compute_hr_zones()['zones']."""
    hr, t = _arr(streams, 'heartrate'), _arr(streams, 'time')
    if hr is None or t is None or not zones or len(hr) != len(t):
        return None
    dt = np.clip(np.diff(t, prepend=t[0]), 0, 30)
    secs = {z: 0.0 for z in ZONE_ORDER}
    for h, w in zip(hr, dt):
        zone = ZONE_ORDER[0]
        for z in ZONE_ORDER:
            if h >= zones[z]['min_bpm']:
                zone = z
        secs[zone] += w
    tot = sum(secs.values()) or 1
    return {f'Z{i + 1}': {'name': z, 'seconds': int(secs[z]), 'pct': round(100 * secs[z] / tot, 1)}
            for i, z in enumerate(ZONE_ORDER)}


def hr_drift(streams: Dict) -> Optional[Dict]:
    """First vs second half (by time): HR and speed, and Pa:HR decoupling in %.

    Decoupling = (EF1 - EF2) / EF1 with EF = grade-adjusted speed / HR; > 5 %
    means the heart rate rose for the same output.
    """
    hr, t = _arr(streams, 'heartrate'), _arr(streams, 'time')
    gap_v = _flat_equiv_speed(streams, altitude_usable(streams))
    if hr is None or gap_v is None or len(hr) != len(t) or t[-1] < 600:
        return None
    mv = _arr(streams, 'moving')
    ok = (mv.astype(bool) if mv is not None and len(mv) == len(t) else np.ones(len(t), bool)) & (hr > 40) & (gap_v > 0.5)
    mid = t[0] + (t[-1] - t[0]) / 2
    out = []
    for sel in (ok & (t < mid), ok & (t >= mid)):
        if sel.sum() < 30:
            return None
        out.append((float(hr[sel].mean()), float(gap_v[sel].mean())))
    (h1, v1), (h2, v2) = out
    ef1, ef2 = v1 / h1, v2 / h2
    return {'hr_first_half': round(h1), 'hr_second_half': round(h2),
            'gap_pace_first_s_km': _pace(v1), 'gap_pace_second_s_km': _pace(v2),
            'decoupling_pct': round((ef1 - ef2) / ef1 * 100, 1)}


def climbs_descents(streams: Dict, top: int = 10) -> List[Dict]:
    """Climbs and descents from the altitude stream (zig-zag with hysteresis)."""
    d, alt = _arr(streams, 'distance'), _arr(streams, 'altitude')
    t, hr = _arr(streams, 'time'), _arr(streams, 'heartrate')
    if d is None or alt is None or len(alt) != len(d):
        return []
    a = _smooth(alt, 9)
    # turning points: a direction flips once altitude moved > hysteresis from the extreme
    pts, lo_i, hi_i, direction = [0], 0, 0, 0
    for i in range(1, len(a)):
        if a[i] >= a[hi_i]:
            hi_i = i
        if a[i] <= a[lo_i]:
            lo_i = i
        if direction <= 0 and a[i] - a[lo_i] > CLIMB_HYSTERESIS_M:
            pts.append(lo_i); direction = 1; hi_i = i
        elif direction >= 0 and a[hi_i] - a[i] > CLIMB_HYSTERESIS_M:
            pts.append(hi_i); direction = -1; lo_i = i
    end = hi_i if direction == 1 else lo_i if direction == -1 else len(a) - 1
    pts.append(max(end, pts[-1]))
    out = []
    for lo, hi in zip(pts[:-1], pts[1:]):
        # trim flat plateaus off both ends (turning points sit at plateau edges)
        sign = 1.0 if a[hi] >= a[lo] else -1.0
        x = sign * a[lo:hi + 1]
        lo, hi = lo + int(np.nonzero(x <= x.min() + 1)[0][-1]), lo + int(np.nonzero(x >= x.max() - 1)[0][0])
        if hi <= lo:
            continue
        dz, length = float(a[hi] - a[lo]), float(d[hi] - d[lo])
        dur = float(t[hi] - t[lo])
        if length < 50 or dur <= 0 or abs(dz) < CLIMB_MIN_GAIN_M or abs(dz) / length * 100 < CLIMB_MIN_GRADE_PCT:
            continue
        item = {'type': 'climb' if dz > 0 else 'descent', 'start_km': round(d[lo] / 1000, 2),
                'length_m': round(length), 'elev_m': round(abs(dz)),
                'grade_pct': round(abs(dz) / length * 100, 1), 'duration_s': int(dur),
                'pace_s_km': _pace(length / dur)}
        if dz > 0:
            item['vam_m_h'] = round(dz / dur * 3600)
        else:
            item['descent_speed_kmh'] = round(length / dur * 3.6, 1)
            item['vertical_speed_m_h'] = round(-dz / dur * 3600)
        if hr is not None and len(hr) == len(d):
            item['hr'] = int(round(float(hr[lo:hi + 1].mean())))
            item['hr_end'] = int(round(float(hr[max(lo, hi - 10):hi + 1].mean())))
        out.append(item)
    out.sort(key=lambda c: -c['elev_m'])
    return sorted(out[:top], key=lambda c: c['start_km'])


def _blocks(sig: np.ndarray, min_contrast: float):
    """Boolean high/low labelling with a midpoint threshold, or None if no contrast."""
    lo, hi = np.percentile(sig, 25), np.percentile(sig, 90)
    if hi - lo < min_contrast:
        return None
    return sig > (lo + hi) / 2


def detect_intervals(streams: Dict) -> Optional[Dict]:
    # TODO(workout-analysis #41 — see GH issues): false positives on hilly easy runs.
    # Activity 342 (easy trail, no structure) gave 16 'work' blocks from climb/descent speed
    # changes. The site hides blocks unless the plan has intervals; MCP still returns them.
    # Fix sketch: detect on GAP speed, or only when the matched plan day has repeat steps.
    """Work/recovery blocks from speed (fallback: heart rate, which lags ~20 s)."""
    t = _arr(streams, 'time')
    if t is None or t[-1] < 300:
        return None
    grid = np.arange(t[0], t[-1], 5.0)
    candidates = []
    v = _arr(streams, 'velocity_smooth')
    if v is not None and len(v) == len(t):
        vs = _smooth(np.interp(grid, t, v), 5)
        candidates.append(('speed', vs, 0.25 * max(float(np.median(vs)), 0.1)))
    hr = _arr(streams, 'heartrate')
    if hr is not None and len(hr) == len(t):
        candidates.append(('hr', _smooth(np.interp(grid, t, hr), 7), 12.0))
    for signal, sig, contrast in candidates:
        hi = _blocks(sig, contrast)
        if hi is None:
            continue
        # run-length encode, absorb flicker shorter than 20 s
        runs = []
        for i, h in enumerate(hi):
            if runs and runs[-1][0] == h:
                runs[-1][2] = i + 1
            else:
                runs.append([bool(h), i, i + 1])
        merged = []
        for r in runs:
            if merged and (r[2] - r[1]) * 5 < 20:
                merged[-1][2] = r[2]
            elif merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        work = [r for r in merged if r[0] and (r[2] - r[1]) * 5 >= MIN_WORK_S]
        if len(work) < MIN_BLOCKS:
            continue
        d = np.interp(grid, t, _arr(streams, 'distance'))
        out = []
        for is_work, a, b in merged:
            dur, dist = (b - a) * 5, float(d[min(b, len(d)) - 1] - d[a])
            blk = {'kind': 'work' if is_work else 'recovery', 'start_s': int(grid[a] - t[0]),
                   'duration_s': dur, 'distance_m': round(dist), 'pace_s_km': _pace(dist / dur)}
            if hr is not None and len(hr) == len(t):
                h = np.interp(grid[a:b], t, hr)
                blk['hr_avg'], blk['hr_max'] = int(h.mean()), int(h.max())
            out.append(blk)
        w = [x for x in out if x['kind'] == 'work']
        return {'signal': signal, 'n_work': len(w),
                'avg_work_s': int(np.mean([x['duration_s'] for x in w])),
                'blocks': out[:MAX_ROWS]}
    return None


def flatten_steps(steps: List[Dict]) -> List[Dict]:
    """Expand repeats into a flat list of non-repeat steps."""
    out = []
    for s in steps or []:
        if s.get('type') == 'repeat':
            out += flatten_steps(s.get('steps', [])) * int(s.get('repeats', 1))
        else:
            out.append(s)
    return out


def step_targets(streams: Dict, steps: List[Dict], zones: Optional[Dict]) -> List[Dict]:
    """Align planned steps to the activity by cumulative planned duration/distance
    and report avg HR / zone vs the step's HR-zone target. Approximate: drifts if
    the runner paused or deviated; stops at the first step with only a D+ measure."""
    t, d = _arr(streams, 'time'), _arr(streams, 'distance')
    hr = _arr(streams, 'heartrate')
    out, pos_t, pos_d = [], float(t[0]), float(d[0])
    for i, s in enumerate(flatten_steps(steps)):
        if s.get('duration_min'):
            t_end = pos_t + s['duration_min'] * 60
        elif s.get('distance_m'):
            t_end = float(np.interp(pos_d + s['distance_m'], d, t, right=t[-1] + 1))
        else:
            break
        if t_end > t[-1] + 1 and pos_t >= t[-1]:
            break
        lo, hi = int(np.searchsorted(t, pos_t)), min(int(np.searchsorted(t, t_end)), len(t) - 1)
        row = {'step': i + 1, 'type': s.get('type'), 'planned_s': int(t_end - pos_t)}
        if hi > lo:
            dist = float(d[hi] - d[lo])
            row['pace_s_km'] = _pace(dist / (t[hi] - t[lo]))
            if hr is not None and len(hr) == len(t):
                row['hr'] = int(hr[lo:hi + 1].mean())
                tgt = s.get('target') or {}
                if tgt.get('type') == 'hr' and tgt.get('zone') and zones:
                    zn = ZONE_ORDER[int(tgt['zone']) - 1]
                    row.update(target_zone=int(tgt['zone']), target_bpm=[zones[zn]['min_bpm'], zones[zn]['max_bpm']],
                               target_met=zones[zn]['min_bpm'] <= row['hr'] <= zones[zn]['max_bpm'])
        out.append(row)
        pos_t = t_end
        pos_d = float(np.interp(t_end, t, d))
    return out


def plan_verdict(planned: Dict, actual: Dict, steps: List[Dict]) -> str:
    """One-line verdict: distance, D+ and HR-target adherence."""
    notes = []
    for key, label, tol in (('distance_km', 'distance', 0.15), ('elevation_m', 'D+', 0.25)):
        p, a = planned.get(key) or 0, actual.get(key) or 0
        if p > 0:
            r = a / p
            notes.append(f'{label} {"on target" if abs(r - 1) <= tol else ("over" if r > 1 else "under")} ({r:.0%} of plan)')
    judged = [s for s in steps if 'target_met' in s]
    if judged:
        notes.append(f'HR target met in {sum(s["target_met"] for s in judged)}/{len(judged)} steps')
    return '; '.join(notes) or 'no comparable plan data'


def summarize(streams: Dict, resolution: str = 'km', zones: Optional[Dict] = None) -> Dict:
    """Full compact analysis of one workout."""
    usable = altitude_usable(streams)
    intervals = detect_intervals(streams)
    if resolution == 'segment':
        rows = splits(streams, 200.0)
    elif resolution == 'lap':
        # laps are not stored: use detected work/recovery blocks, else km splits
        rows = intervals['blocks'] if intervals else splits(streams)
    else:
        rows = splits(streams)
    out = {'resolution': resolution if resolution != 'lap' or intervals else 'km (no laps/blocks found)',
           'splits': rows, 'altitude_available': usable,
           'hr_zones': hr_zone_times(streams, zones), 'hr_drift': hr_drift(streams),
           'intervals': intervals}
    if usable:
        out['climbs_descents'] = climbs_descents(streams)
    else:
        out['climbs_descents'] = None
        out['altitude_note'] = ('Altitude unavailable or flat (treadmill/indoor): climbs and D+ cannot be '
                                'measured from the data. Use the planned incline of the matched plan day.')
    return out

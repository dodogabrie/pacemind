"""Heart-rate intensity for the Tier 2 calibration.

Tier 2 measures v_flat on the user's last 10 runs, i.e. at whatever intensity
those runs were done. A polarised runner (mostly very easy, short hard bursts)
gets an easy-pace v_flat and a race prediction that is far too slow. Here we
learn, from every minute of the user's runs including the bursts, how speed
(relative to the physics model on that grade) moves with heart rate:

    log(v_actual / v_model(grade)) = a + b * log(%HRR) + c * hours_elapsed

%HRR = (HR - HRrest) / (HRmax - HRrest) (Karvonen), HR taken 30 s later than
the speed it answers (HR lags effort), first 10 min dropped (HR still rising),
and the elapsed-hours term soaks up cardiac drift so it does not bias b. b is
shrunk toward 1, the prior "speed is proportional to %VO2 reserve" (ACSM
running equation, VO2 = 0.2*speed + 3.5) with %HRR ~ %VO2R (Swain & Leutholtz
1997, MSSE 29:410). The prediction at intensity I is Tier 2 x (I / I_ref)^-b,
I_ref being the typical intensity of the calibration runs.

Race intensity falls with duration. Prior (documented, shrinkable, NOT fitted
here): %HRR = 0.87 - 0.09 ln(hours), clipped to [0.50, 0.90], i.e. ~87 % for
1 h, ~77 % for a marathon-length 3 h, ~66 % for 10 h, ~58 % for 24 h. Anchored
to commonly reported field values (marathon ~80-85 % HRmax; long mountain
ultras ~65-75 % HRmax falling with duration, e.g. Fornasiero et al. 2018 J
Sports Sci 36:1287); treat the exact numbers as approximate. Each confirmed
race with HR moves the user's curve toward what they actually held
(offset shrunk like n / (n + 1)).
"""
# TODO(pred-review #40 — see GH issues): fitted b (~0.4 on user 3) is well below
# the prior 1, likely errors-in-variables attenuation from minute-level HR/grade
# noise; HRrest defaults to 60 bpm; the race-intensity prior anchors need checking
# against the papers; Tier 3 does not yet take intensity as a feature.

import math
from typing import Dict, List, Optional

import numpy as np

from services.physics_model.pipeline import velocity_at_grade

HR_LAG_S = 30
WARMUP_S = 600
CHUNK_S = 60
DEFAULT_HR_REST = 60      # bpm; resting HR is not observable from running data
HR_MAX_QUANTILE = 99.5    # of 30 s smoothed HR over the user's runs
MIN_HR_ACTIVITIES = 3
WINDOW = 30               # most recent runs used for the fit (bursts are rare)
PRIOR_B = 1.0
PRIOR_STRENGTH = 5 * 0.02  # ~5 runs' worth of log-intensity spread
# A confirmed race's HR is a direct measure of how hard this user races, so it
# outweighs the population prior quickly: one race = half, two = two thirds.
# (K = 3 left user 3's two races at 139-145 bpm vs the 151 they held over 5 h.)
RACE_PRIOR_K = 1


def race_intensity_prior(hours: float) -> float:
    return float(np.clip(0.87 - 0.09 * math.log(max(hours, 0.25)), 0.50, 0.90))


def _hr(streams: Dict) -> Optional[np.ndarray]:
    hr = streams.get('heartrate')
    if not hr or 'time' not in streams or len(hr) != len(streams['time']):
        return None
    hr = np.asarray(hr, dtype=float)
    return hr if np.nanmedian(hr) > 60 else None


def hr_bounds(activities: List, hr_max: Optional[int] = None, hr_rest: Optional[int] = None):
    """(HRmax, HRrest): the profile's values, else a high quantile of 30 s smoothed HR / 60 bpm."""
    if not hr_max:
        smooth = []
        for a in activities:
            hr = _hr(a.streams or {})
            if hr is not None and len(hr) > 30:
                smooth.append(np.convolve(hr, np.ones(30) / 30, mode='valid'))
        if len(smooth) < MIN_HR_ACTIVITIES:
            return None, None
        hr_max = float(np.percentile(np.concatenate(smooth), HR_MAX_QUANTILE))
    return float(hr_max), float(hr_rest or DEFAULT_HR_REST)


def chunks(streams: Dict, params: Dict, hr_max: float, hr_rest: float) -> Optional[Dict[str, np.ndarray]]:
    """One row per moving minute after warm-up: log speed ratio, log %HRR, hours elapsed."""
    hr = _hr(streams)
    if hr is None or not all(k in streams for k in ('distance', 'altitude')):
        return None
    t = np.asarray(streams['time'], dtype=float)
    d = np.asarray(streams['distance'], dtype=float)
    z = np.asarray(streams['altitude'], dtype=float)
    moving = np.asarray(streams.get('moving') or [True] * len(t), dtype=bool)
    edges = np.arange(WARMUP_S, t[-1] - CHUNK_S - HR_LAG_S, CHUNK_S)
    if len(edges) < 2:
        return None
    idx = np.searchsorted(t, edges)
    lag = np.searchsorted(t, edges + HR_LAG_S)
    rows = []
    for k in range(len(edges) - 1):
        i0, i1, h0, h1 = idx[k], idx[k + 1], lag[k], lag[k + 1]
        if i1 - i0 < 10 or h1 - h0 < 10 or not moving[i0:i1].all():
            continue
        dd = d[i1] - d[i0]
        speed = dd / (t[i1] - t[i0])
        if not (0.5 < speed < 7) or dd < 20:
            continue
        g = (z[i1] - z[i0]) / dd
        if abs(g) > 0.35:
            continue
        hrr = (np.mean(hr[h0:h1]) - hr_rest) / (hr_max - hr_rest)
        v_model = velocity_at_grade(g, params['v_flat'], params['k_up'], params['k_tech'], params['a_param'],
                                    params.get('k_terrain_up', 1.08), params.get('k_terrain_down', 1.12),
                                    params.get('k_terrain_flat', 1.05))
        rows.append((math.log(speed / v_model), math.log(min(1.0, max(0.2, hrr))), t[i0] / 3600))
    if len(rows) < 10:
        return None
    y, li, th = map(np.array, zip(*rows))
    return {'log_r': y, 'log_i': li, 'hours': th}


def fit(activities: List, params: Dict, hr_max: Optional[int] = None, hr_rest: Optional[int] = None,
        ref_activities: Optional[List] = None) -> Optional[Dict]:
    """Intensity model on the last WINDOW runs; I_ref from ref_activities (the Tier 2 window)."""
    window = activities[-WINDOW:]
    hr_max, hr_rest = hr_bounds(window, hr_max, hr_rest)
    if hr_max is None or hr_max <= hr_rest + 40:
        return None
    per_act = [(a, c) for a in window if (c := chunks(a.streams or {}, params, hr_max, hr_rest))]
    if len(per_act) < MIN_HR_ACTIVITIES:
        return None
    y = np.concatenate([c['log_r'] for _, c in per_act])
    X = np.column_stack([np.ones_like(y), np.concatenate([c['log_i'] for _, c in per_act]),
                         np.concatenate([c['hours'] for _, c in per_act])])
    w = np.concatenate([np.full(len(c['log_r']), 1.0 / len(c['log_r'])) for _, c in per_act])
    # Weighted least squares with a Gaussian prior on b only (toward PRIOR_B).
    lam = np.diag([0.0, PRIOR_STRENGTH, 0.0])
    theta = np.linalg.solve(X.T @ (w[:, None] * X) + lam,
                            X.T @ (w * y) + lam @ np.array([0.0, PRIOR_B, 0.0]))
    ref = [c for a, c in per_act if a in (ref_activities or window)] or [c for _, c in per_act]
    i_ref = float(np.exp(np.median(np.concatenate([c['log_i'] for c in ref]))))
    return {'a': float(theta[0]), 'b': float(theta[1]), 'drift_per_h': float(theta[2]), 'i_ref': i_ref,
            'hr_max': hr_max, 'hr_rest': hr_rest, 'n_activities': len(per_act), 'n_minutes': int(len(y))}


def observed_intensity(streams: Dict, params: Dict, model: Dict) -> Optional[float]:
    """Median %HRR a run was done at (same chunking as the fit)."""
    c = chunks(streams, params, model['hr_max'], model['hr_rest'])
    return float(np.exp(np.median(c['log_i']))) if c else None


def time_multiplier(model: Dict, intensity: float) -> float:
    """Tier 2 moving time x this = moving time at `intensity` (%HRR, 0-1)."""
    return float((intensity / model['i_ref']) ** -model['b'])


def race_offset(races: List[Dict]) -> float:
    """races: [{'intensity', 'hours'}] of confirmed races with HR -> shrunk shift of the prior."""
    if not races:
        return 0.0
    diffs = [r['intensity'] - race_intensity_prior(r['hours']) for r in races]
    return float(sum(diffs) / (len(diffs) + RACE_PRIOR_K))


def effort_intensity(model: Dict, effort: str, hours: float) -> float:
    if effort == 'race':
        return float(np.clip(race_intensity_prior(hours) + model.get('race_offset', 0.0), 0.4, 0.95))
    if effort == 'recovery':
        return 0.9 * model['i_ref']
    return model['i_ref']


def moving_at_effort(model: Dict, effort: str, tier2_moving_s: float) -> Dict:
    """Moving time at the effort's intensity; race intensity depends on the race's own duration."""
    t = tier2_moving_s
    for _ in range(3):  # fixed point: duration -> intensity -> duration
        i = effort_intensity(model, effort, t / 3600)
        t = tier2_moving_s * time_multiplier(model, i)
    lo, hi = max(0.0, i - 0.03), min(1.0, i + 0.03)
    return {'moving_s': t, 'intensity': i, 'hr_low': intensity_to_hr(model, lo), 'hr_high': intensity_to_hr(model, hi),
            'target_hr': intensity_to_hr(model, i), 'verdict': sustainability(model, i, t / 3600)}


def hr_to_intensity(model: Dict, hr: float) -> float:
    return (hr - model['hr_rest']) / (model['hr_max'] - model['hr_rest'])


def intensity_to_hr(model: Dict, i: float) -> int:
    return int(round(model['hr_rest'] + i * (model['hr_max'] - model['hr_rest'])))


def moving_at_hr(model: Dict, hr: float, tier2_moving_s: float) -> Dict:
    """Moving time if the user holds `hr` for the whole race, plus how realistic that is."""
    i = float(np.clip(hr_to_intensity(model, hr), 0.2, 1.0))
    t = tier2_moving_s * time_multiplier(model, i)
    return {'moving_s': t, 'intensity': i, 'target_hr': int(round(hr)),
            'hr_low': int(round(hr)), 'hr_high': int(round(hr)),
            'verdict': sustainability(model, i, t / 3600)}


# Verdict bands in %HRR points around the user's own race intensity for that
# duration (prior + learned race offset). ponytail: fixed bands; fit them on
# confirmed races (predicted vs held HR, fade in the last quarter) when there
# are enough races across users' own histories.
EASY_BELOW = -0.05
OK_UP_TO = 0.02
HARD_UP_TO = 0.06
MIN_BEST_HOURS_SHARE = 0.75   # "held for at least 3/4 of this race's duration"


def sustainability(model: Dict, i: float, hours: float) -> Dict:
    """How hard holding intensity `i` for `hours` is for this user.

    level: easy | sustainable | hard | too_hard. `race_hr` is what the user
    usually holds in a race this long; `best` is the highest median HR they
    actually held over a run at least 3/4 this long (from `model['efforts']`)."""
    race_i = effort_intensity(model, 'race', hours)
    long_enough = [e for e in model.get('efforts', []) if e['hours'] >= MIN_BEST_HOURS_SHARE * hours]
    best = max(long_enough, key=lambda e: e['intensity'], default=None)
    delta = i - race_i
    if delta <= EASY_BELOW:
        level = 'easy'
    elif delta <= OK_UP_TO:
        level = 'sustainable'
    elif delta <= HARD_UP_TO and (best is None or i <= best['intensity'] + OK_UP_TO):
        level = 'hard'
    else:
        level = 'too_hard'
    return {
        'level': level,
        'race_hr': intensity_to_hr(model, race_i),
        'best': {'hr': intensity_to_hr(model, best['intensity']), 'hours': round(best['hours'], 1),
                 'name': best.get('name'), 'date': best.get('date')} if best else None,
    }


def efforts(acts: List, params: Dict, model: Dict) -> List[Dict]:
    """Median intensity the user held on each run with HR of 1 h or more (for `sustainability`)."""
    out = []
    for a in acts:
        hours = (a.moving_time_s or 0) / 3600
        if hours < 1:
            continue
        i = observed_intensity(a.streams, params, model)
        if i:
            out.append({'hours': round(hours, 2), 'intensity': round(i, 4), 'name': a.name,
                        'date': a.start_date.date().isoformat() if a.start_date else None})
    return out


def profile_hr(user_id: int):
    """(hr_max, hr_rest) the user entered in training preferences, or (None, None)."""
    from models import UserTrainingPreferences
    p = UserTrainingPreferences.query.filter_by(user_id=user_id).first()
    return (p.hr_max, p.hr_rest) if p else (None, None)

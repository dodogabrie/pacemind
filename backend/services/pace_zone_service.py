"""Pace zone service - compute default zones from flat pace, store/retrieve overrides."""

from typing import Dict, Iterable, List, Optional, Tuple


# Zone multipliers relative to flat_pace (min/km)
# Higher multiplier = slower pace
ZONE_DEFINITIONS = {
    'recovery':  {'min_mult': 1.25, 'max_mult': 1.35, 'rpe': '1-2', 'description': 'Walk/easy jog'},
    'easy':      {'min_mult': 1.10, 'max_mult': 1.25, 'rpe': '3-4', 'description': 'Conversational'},
    'tempo':     {'min_mult': 0.92, 'max_mult': 1.00, 'rpe': '5-6', 'description': 'Comfortably hard'},
    'threshold': {'min_mult': 0.85, 'max_mult': 0.92, 'rpe': '7-8', 'description': 'Hard/threshold'},
    'interval':  {'min_mult': 0.78, 'max_mult': 0.85, 'rpe': '9-10', 'description': 'Max effort'},
}

# Zone display order
ZONE_ORDER = ['recovery', 'easy', 'tempo', 'threshold', 'interval']


def compute_default_zones(flat_pace_min_per_km: float) -> Dict:
    """Compute default pace zones from flat pace.

    Args:
        flat_pace_min_per_km: Flat pace in minutes per km (e.g. 5.0 for 5:00/km)

    Returns:
        Dict of zone_name -> {min_pace, max_pace, rpe, description}
        Paces are in min/km (float). Lower min_pace = faster.
    """
    zones = {}
    for zone_name in ZONE_ORDER:
        defn = ZONE_DEFINITIONS[zone_name]
        zones[zone_name] = {
            'min_pace': round(flat_pace_min_per_km * defn['min_mult'], 2),
            'max_pace': round(flat_pace_min_per_km * defn['max_mult'], 2),
            'rpe': defn['rpe'],
            'description': defn['description'],
        }
    return zones


VALID_PACE_ZONE_METHODS = {'physics', 'vdot', 'riegel'}


def compute_zones_by_method(method: str, *, v_flat_ms: float,
                            race_distance_m: Optional[float] = None,
                            race_time_s: Optional[float] = None) -> Dict:
    """Derive pace zones via the user's chosen method.

    Args:
        method: one of VALID_PACE_ZONE_METHODS. Unknown values fall back to physics.
        v_flat_ms: physics-extracted flat speed (m/s), used by physics mode and
            as a fallback when race inputs are missing.
        race_distance_m / race_time_s: a recent race result; required for vdot
            and riegel modes.

    Returns:
        {'zones': {...}, 'method': str, 'meta': {...}}. ``method`` reflects the
        method actually applied (may differ from the request on fallback).
    """
    flat_pace = flat_speed_to_pace(v_flat_ms)
    has_race = bool(race_distance_m and race_time_s)

    if method in ('vdot', 'riegel') and has_race:
        from services.vdot_service import (
            vdot_from_race, vdot_zones, riegel_flat_pace,
        )
        if method == 'vdot':
            vdot = vdot_from_race(race_distance_m, race_time_s)
            return {
                'zones': vdot_zones(vdot),
                'method': 'vdot',
                'meta': {'vdot': round(vdot, 1),
                         'race_distance_m': race_distance_m,
                         'race_time_s': race_time_s},
            }
        riegel_pace = riegel_flat_pace(race_distance_m, race_time_s)
        return {
            'zones': compute_default_zones(riegel_pace),
            'method': 'riegel',
            'meta': {'riegel_flat_pace': round(riegel_pace, 2),
                     'race_distance_m': race_distance_m,
                     'race_time_s': race_time_s},
        }

    # physics (default) or vdot/riegel requested without a race result.
    return {
        'zones': compute_default_zones(flat_pace),
        'method': 'physics',
        'meta': {'flat_pace_min_per_km': round(flat_pace, 2)},
    }


# --- Heart-rate zones (#59) -------------------------------------------------
# Each band is (low_frac, high_frac) of the basis anchor. low_frac -> lower bpm
# end of the zone, high_frac -> upper bpm end. Bands map onto the same five
# zones used for pace so a workout's zone label resolves consistently.

# Karvonen / HR-reserve fractions (Daniels' DRF guidance, HRR = hr_max - hr_rest).
_HR_KARVONEN_BANDS = {
    'recovery':  (0.50, 0.60),
    'easy':      (0.60, 0.70),
    'tempo':     (0.80, 0.87),
    'threshold': (0.87, 0.92),
    'interval':  (0.92, 0.97),
}

# Percent of HR-max fallback (used when resting HR is unknown).
_HR_PCT_MAX_BANDS = {
    'recovery':  (0.60, 0.70),
    'easy':      (0.70, 0.80),
    'tempo':     (0.80, 0.87),
    'threshold': (0.87, 0.92),
    'interval':  (0.92, 0.97),
}

# Percent of lactate-threshold HR (Friel). Threshold sits at 100% LTHR; the top
# zone runs above it. Most accurate anchor when a field/lab LTHR is known.
_HR_LTHR_BANDS = {
    'recovery':  (0.80, 0.85),
    'easy':      (0.85, 0.90),
    'tempo':     (0.90, 0.95),
    'threshold': (0.95, 1.00),
    'interval':  (1.00, 1.06),
}

_VALID_HR_MAX = (100, 240)
_VALID_HR_REST = (25, 120)
_VALID_LTHR = (80, 230)


def compute_hr_zones(hr_max: Optional[int] = None,
                     hr_rest: Optional[int] = None,
                     lthr: Optional[int] = None) -> Optional[Dict]:
    """Derive heart-rate training zones (bpm) from the available anchors.

    Basis is chosen by accuracy, in priority order:
      1. ``lthr`` present -> %LTHR bands (Friel).
      2. ``hr_max`` and ``hr_rest`` present -> Karvonen / HR-reserve.
      3. ``hr_max`` only -> %HR-max bands.
      4. nothing usable -> ``None``.

    bpm values are capped at ``hr_max`` when it is known and rounded to ints.

    Returns:
        ``{'basis': str, 'zones': {...}, 'inputs': {...}}`` or ``None``.
    """
    hr_max = _coerce_int(hr_max)
    hr_rest = _coerce_int(hr_rest)
    lthr = _coerce_int(lthr)

    if lthr and lthr > 0:
        basis, bands = 'lthr', _HR_LTHR_BANDS
        base, reserve = lthr, 0           # bpm = base*frac + reserve*frac (reserve=0)
    elif hr_max and hr_rest and hr_max > hr_rest:
        basis, bands = 'karvonen', _HR_KARVONEN_BANDS
        base, reserve = hr_rest, hr_max - hr_rest  # bpm = hr_rest + HRR*frac
    elif hr_max and hr_max > 0:
        basis, bands = 'pct_hr_max', _HR_PCT_MAX_BANDS
        base, reserve = hr_max, 0         # bpm = hr_max*frac
    else:
        return None

    # Karvonen anchors off resting HR (base + reserve*frac); the %-of-anchor
    # bases scale the anchor directly, expressed here as base*frac with no offset.
    if basis == 'karvonen':
        def to_bpm(frac):
            return base + reserve * frac
    else:
        def to_bpm(frac):
            return base * frac

    zones = {}
    for zone_name in ZONE_ORDER:
        low, high = bands[zone_name]
        meta = ZONE_DEFINITIONS[zone_name]
        min_bpm = _cap_bpm(to_bpm(low), hr_max)
        max_bpm = _cap_bpm(to_bpm(high), hr_max)
        if max_bpm < min_bpm:
            max_bpm = min_bpm
        zones[zone_name] = {
            'min_bpm': min_bpm,
            'max_bpm': max_bpm,
            'rpe': meta['rpe'],
            'description': meta['description'],
        }

    return {
        'basis': basis,
        'zones': zones,
        'inputs': {'hr_max': hr_max, 'hr_rest': hr_rest, 'lthr': lthr},
    }


def _cap_bpm(value: float, hr_max: Optional[int]) -> int:
    bpm = int(round(value))
    if hr_max and bpm > hr_max:
        return hr_max
    return bpm


def _coerce_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def estimate_hr_max_from_streams(streams_iterable, multiplier: float = 1.02) -> Optional[int]:
    """Estimate HR-max from observed heart-rate samples in activity streams.

    Takes the global maximum valid HR sample across the given streams and scales
    it by ``multiplier`` (default ×1.02, allowing for samples slightly below the
    true ceiling). Samples outside (0, 220) are discarded as artefacts — the same
    bounds segmentation uses.

    Args:
        streams_iterable: iterable of stream dicts, each optionally carrying a
            ``'heartrate'`` list of bpm samples.

    Returns:
        Estimated HR-max (int) or ``None`` if no valid samples were found.
    """
    observed_max = 0
    for streams in streams_iterable:
        if not isinstance(streams, dict):
            continue
        for hr in streams.get('heartrate') or []:
            try:
                hr = float(hr)
            except (TypeError, ValueError):
                continue
            if 0 < hr < 220 and hr > observed_max:
                observed_max = hr
    if observed_max <= 0:
        return None
    return int(round(observed_max * multiplier))


# --- Running-power zones (#60) ---------------------------------------------
# Coggan-style zones expressed as fractions of FTP (functional threshold
# power), collapsed onto the same five zone names used for pace/HR so a
# workout's zone label resolves consistently across anchors. FTP itself sits
# at ~100% (the tempo/threshold boundary). Bands follow the issue's 5-band
# simplification of the classic 7-zone model: Z1 <80%, Z2 80-90%, Z3 90-100%,
# Z4 100-115%, Z5 >115% FTP.
_POWER_COGGAN_BANDS = {
    'recovery':  (0.50, 0.80),
    'easy':      (0.80, 0.90),
    'tempo':     (0.90, 1.00),
    'threshold': (1.00, 1.15),
    'interval':  (1.15, 1.50),
}

_VALID_FTP_W = (50, 600)


def compute_power_zones(ftp_w: Optional[int] = None) -> Optional[Dict]:
    """Derive running-power training zones (watts) from FTP.

    Args:
        ftp_w: functional threshold power in watts. ``None`` or non-positive
            yields ``None`` (no power anchor set).

    Returns:
        ``{'zones': {...}, 'inputs': {'ftp_w': int}}`` or ``None``. Each zone
        carries ``min_w`` / ``max_w`` (ints) plus the shared rpe/description.
    """
    ftp_w = _coerce_int(ftp_w)
    if not ftp_w or ftp_w <= 0:
        return None

    zones = {}
    for zone_name in ZONE_ORDER:
        low, high = _POWER_COGGAN_BANDS[zone_name]
        meta = ZONE_DEFINITIONS[zone_name]
        zones[zone_name] = {
            'min_w': int(round(ftp_w * low)),
            'max_w': int(round(ftp_w * high)),
            'rpe': meta['rpe'],
            'description': meta['description'],
        }

    return {'zones': zones, 'inputs': {'ftp_w': ftp_w}}


def estimate_ftp_from_streams(streams_iterable: Iterable, window_s: int = 1200,
                              factor: float = 0.95) -> Optional[int]:
    """Estimate FTP from the best rolling 20-minute average power in streams.

    The standard field protocol: take the highest average power sustained over
    ``window_s`` seconds (default 20 min) across the supplied activities, then
    scale by ``factor`` (default ×0.95). A single global max-watts sample would
    just be a sprint spike, so the time-windowed mean is required for a
    meaningful estimate.

    Args:
        streams_iterable: iterable of stream dicts, each optionally carrying a
            ``'watts'`` list and an aligned ``'time'`` list (seconds from start).
            When ``'time'`` is missing or misaligned, 1 Hz sampling is assumed.

    Returns:
        Estimated FTP in watts (int) or ``None`` if no activity covers a full
        window of valid power data.
    """
    best_avg = 0.0
    for streams in streams_iterable:
        if not isinstance(streams, dict):
            continue
        avg = _best_window_avg(streams.get('watts') or [],
                               streams.get('time') or [], window_s)
        if avg > best_avg:
            best_avg = avg
    if best_avg <= 0:
        return None
    return int(round(best_avg * factor))


def _best_window_avg(watts: List, times: List, window_s: int) -> float:
    """Best mean power over any ``window_s``-second window in one activity."""
    pairs: List[Tuple[float, float]] = []
    use_time = len(times) == len(watts)
    for i, w in enumerate(watts):
        try:
            watt = float(w)
        except (TypeError, ValueError):
            continue
        if watt < 0:
            continue
        if use_time:
            try:
                t = float(times[i])
            except (TypeError, ValueError):
                continue
        else:
            t = float(i)  # assume 1 Hz
        pairs.append((t, watt))

    if len(pairs) < 2:
        return 0.0
    pairs.sort(key=lambda p: p[0])
    if pairs[-1][0] - pairs[0][0] < window_s * 0.9:
        return 0.0  # activity shorter than the window — can't estimate FTP

    best = 0.0
    win_sum = 0.0
    start = 0
    for end in range(len(pairs)):
        win_sum += pairs[end][1]
        while pairs[end][0] - pairs[start][0] > window_s:
            win_sum -= pairs[start][1]
            start += 1
        count = end - start + 1
        if count > 0 and pairs[end][0] - pairs[start][0] >= window_s * 0.9:
            avg = win_sum / count
            if avg > best:
                best = avg
    return best


def flat_speed_to_pace(v_flat_ms: float) -> float:
    """Convert flat speed (m/s) to pace (min/km)."""
    if v_flat_ms <= 0:
        return 6.0  # fallback
    return (1000 / v_flat_ms) / 60


def merge_zone_overrides(default_zones: Dict, overrides: Optional[Dict]) -> Dict:
    """Merge user overrides into default zones.

    Overrides is a dict of zone_name -> {min_pace, max_pace}.
    Only overridden fields are replaced.
    """
    if not overrides:
        return default_zones

    merged = {}
    for zone_name in ZONE_ORDER:
        base = default_zones.get(zone_name, {}).copy()
        user = overrides.get(zone_name, {})
        if user.get('min_pace') is not None:
            base['min_pace'] = user['min_pace']
        if user.get('max_pace') is not None:
            base['max_pace'] = user['max_pace']
        merged[zone_name] = base
    return merged


def format_pace(pace_min_per_km: float) -> str:
    """Format pace as M:SS/km string."""
    minutes = int(pace_min_per_km)
    seconds = int((pace_min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def resolve_pace_target(zone_name: str, zones: Dict) -> Optional[Dict]:
    """Resolve a zone name to a pace range.

    Returns:
        {min_pace: float, max_pace: float, display: str} or None
    """
    zone = zones.get(zone_name)
    if not zone:
        return None
    return {
        'min_pace': zone['min_pace'],
        'max_pace': zone['max_pace'],
        'display': f"{format_pace(zone['min_pace'])}-{format_pace(zone['max_pace'])}/km",
    }

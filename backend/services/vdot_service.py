"""VDOT (Daniels) and Riegel pace-zone derivation from a recent race result.

Two alternative anchors to the physics-extracted v_flat:

* **VDOT** — Daniels' aerobic-power proxy computed from one race (distance, time).
  Training intensities are expressed as a fraction of VDOT and converted back to
  a pace via the inverse of Daniels' VO2-velocity relation.
* **Riegel** — endurance time predictor t2 = t1 * (d2/d1)^exponent. We project the
  race to marathon distance to obtain a sustainable flat pace, then reuse the
  existing multiplier zone model (see pace_zone_service.compute_default_zones).

References:
  Daniels, J. (2014). Daniels' Running Formula, 3rd ed. — VDOT tables.
  Riegel, P. S. (1981). Athletic records and human endurance. Am Sci 69:285-290.
"""

import math
from typing import Dict


# --- Daniels VO2 <-> velocity coefficients (velocity in m/min) ---
_VO2_A = 0.000104   # quadratic
_VO2_B = 0.182258   # linear
_VO2_C = -4.60      # constant

# %VDOT intensity bands mapped onto the project's five zones.
# (low_frac, high_frac): high_frac -> faster pace (min_pace), low_frac -> slower
# pace (max_pace). Bands follow Daniels' E/M/T/I/R guidance, collapsed to the
# recovery/easy/tempo/threshold/interval taxonomy used elsewhere.
_VDOT_BANDS = {
    'recovery':  (0.60, 0.70),
    'easy':      (0.70, 0.78),
    'tempo':     (0.78, 0.86),   # marathon -> tempo
    'threshold': (0.86, 0.92),
    'interval':  (0.95, 1.00),
}

_ZONE_META = {
    'recovery':  {'rpe': '1-2', 'description': 'Walk/easy jog'},
    'easy':      {'rpe': '3-4', 'description': 'Conversational'},
    'tempo':     {'rpe': '5-6', 'description': 'Comfortably hard'},
    'threshold': {'rpe': '7-8', 'description': 'Hard/threshold'},
    'interval':  {'rpe': '9-10', 'description': 'Max effort'},
}

RIEGEL_EXPONENT = 1.06
_MARATHON_M = 42195.0


def vdot_from_race(distance_m: float, time_s: float) -> float:
    """Compute Daniels' VDOT from a single race result.

    Args:
        distance_m: race distance in metres (> 0)
        time_s: finishing time in seconds (> 0)

    Returns:
        VDOT (ml/kg/min, pseudo-VO2max).

    Raises:
        ValueError: on non-positive inputs.
    """
    if distance_m <= 0 or time_s <= 0:
        raise ValueError('distance_m and time_s must be positive')

    t_min = time_s / 60.0
    v = distance_m / t_min  # m/min
    pct_max = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t_min)
        + 0.2989558 * math.exp(-0.1932605 * t_min)
    )
    vo2 = _VO2_C + _VO2_B * v + _VO2_A * v * v
    return vo2 / pct_max


def _velocity_for_vo2(vo2: float) -> float:
    """Invert Daniels' VO2-velocity relation. Returns velocity in m/min."""
    # Solve _VO2_A v^2 + _VO2_B v + (_VO2_C - vo2) = 0 for the positive root.
    disc = _VO2_B * _VO2_B - 4 * _VO2_A * (_VO2_C - vo2)
    if disc <= 0:
        return 0.0
    return (-_VO2_B + math.sqrt(disc)) / (2 * _VO2_A)


def _vo2_fraction_to_pace(vdot: float, frac: float) -> float:
    """Pace (min/km) for a given fraction of VDOT."""
    v = _velocity_for_vo2(vdot * frac)  # m/min
    if v <= 0:
        return 99.0
    return 1000.0 / v


def vdot_zones(vdot: float) -> Dict:
    """Derive pace zones (min/km) from a VDOT using Daniels' intensity bands."""
    zones = {}
    for zone_name, (low, high) in _VDOT_BANDS.items():
        # Higher intensity fraction -> faster pace (smaller number).
        min_pace = _vo2_fraction_to_pace(vdot, high)
        max_pace = _vo2_fraction_to_pace(vdot, low)
        meta = _ZONE_META[zone_name]
        zones[zone_name] = {
            'min_pace': round(min_pace, 2),
            'max_pace': round(max_pace, 2),
            'rpe': meta['rpe'],
            'description': meta['description'],
        }
    return zones


def riegel_predict_time(d1_m: float, t1_s: float, d2_m: float,
                        exponent: float = RIEGEL_EXPONENT) -> float:
    """Project a finishing time to another distance via Riegel's model.

    t2 = t1 * (d2 / d1) ** exponent

    Raises:
        ValueError: on non-positive inputs.
    """
    if d1_m <= 0 or t1_s <= 0 or d2_m <= 0:
        raise ValueError('distances and time must be positive')
    return t1_s * (d2_m / d1_m) ** exponent


def riegel_flat_pace(distance_m: float, time_s: float,
                     exponent: float = RIEGEL_EXPONENT) -> float:
    """Estimate a sustainable flat pace (min/km) by projecting the race to the
    marathon distance.

    Marathon pace is a good proxy for the physics model's ``v_flat`` anchor,
    so the projected pace can feed the existing multiplier zone model.
    """
    t_marathon_s = riegel_predict_time(distance_m, time_s, _MARATHON_M, exponent)
    return (t_marathon_s / 60.0) / (_MARATHON_M / 1000.0)

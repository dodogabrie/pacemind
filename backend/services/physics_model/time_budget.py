"""Hours <-> km/elevation conversions for time-first onboarding.

Thin layer on top of physics_model.core. Used by:
- the onboarding wizard (live preview of "what does 6h/week mean for you?")
- the agent's preview_capacity tool
- plan_engine's weekly_hours_above_cap warning

Falls back to median trail-runner constants when learned params are absent.
"""
from __future__ import annotations

from typing import Optional

from services.physics_model.core import predict_uphill_velocity


# Median-runner defaults, used when UserLearnedParams is missing.
# v_flat tuned so a 6:30/km easy pace is roughly the baseline.
DEFAULT_V_FLAT_M_S = 1000.0 / (6.5 * 60.0)  # ~2.564 m/s ≈ 6:30/km
DEFAULT_K_UP = 1.0
DEFAULT_K_TERRAIN = 1.08  # gentle trail penalty

# Effort discount on flat velocity. easy/long_run runners go slower than threshold.
EFFORT_V_FLAT_DISCOUNT = {
    'easy':       0.85,
    'long_run':   0.78,
    'tempo':      0.93,
    'recovery':   0.78,
    'easy_pickups': 0.85,
    'easy_strides': 0.85,
}


def _resolve_params(learned_params) -> tuple[float, float, float]:
    """Pull (v_flat, k_up, k_terrain) from UserLearnedParams or use defaults.

    Accepts a model instance, dict, or None. Always returns sane numbers.
    """
    if learned_params is None:
        return DEFAULT_V_FLAT_M_S, DEFAULT_K_UP, DEFAULT_K_TERRAIN

    def _get(obj, key, default):
        if isinstance(obj, dict):
            return obj.get(key, default) or default
        return getattr(obj, key, default) or default

    v_flat = float(_get(learned_params, 'v_flat', DEFAULT_V_FLAT_M_S))
    k_up = float(_get(learned_params, 'k_up', DEFAULT_K_UP))
    k_terrain = float(_get(learned_params, 'k_terrain', DEFAULT_K_TERRAIN))
    return v_flat, k_up, k_terrain


def _effort_v_flat(v_flat: float, effort: str) -> float:
    discount = EFFORT_V_FLAT_DISCOUNT.get(effort, EFFORT_V_FLAT_DISCOUNT['easy'])
    return v_flat * discount


def predict_time_for_distance(
    km: float,
    m_d_plus: float,
    learned_params=None,
    effort: str = 'long_run',
) -> float:
    """Estimate the runner's wall-clock hours for (km, m_d+) at the given effort.

    Splits into a flat-equivalent (km - climb) + uphill segment using Minetti
    cost ratio. Inverse of predict_distance_for_time below.
    """
    if km <= 0:
        return 0.0
    v_flat, k_up, k_terrain = _resolve_params(learned_params)
    v_eff = _effort_v_flat(v_flat, effort)

    # Avg grade across the run (positive only — descents priced at flat pace).
    horizontal_m = km * 1000.0
    if m_d_plus <= 0:
        return horizontal_m / v_eff / 3600.0

    avg_grade = m_d_plus / horizontal_m
    v_up = predict_uphill_velocity(
        grade=avg_grade,
        v_flat=v_eff,
        k_up=k_up,
        k_terrain=k_terrain,
    )
    if v_up <= 0:
        return horizontal_m / v_eff / 3600.0
    return horizontal_m / v_up / 3600.0


def predict_distance_for_time(
    hours: float,
    training_ratio_m_per_km: float,
    learned_params=None,
    effort: str = 'long_run',
) -> tuple[float, float]:
    """Inverse of predict_time_for_distance.

    Given an hour budget and a target elevation density (m D+ per km), return
    (km, m_d_plus) the runner can realistically cover at the requested effort.
    """
    if hours <= 0:
        return 0.0, 0.0
    v_flat, k_up, k_terrain = _resolve_params(learned_params)
    v_eff = _effort_v_flat(v_flat, effort)

    if training_ratio_m_per_km <= 0:
        # Pure flat — direct conversion.
        km = (v_eff * hours * 3600.0) / 1000.0
        return round(km, 1), 0.0

    # Closed-form approximation: at avg grade g = ratio/1000, the uphill
    # velocity is v_eff / cost_ratio(g). We use that as the running velocity
    # for the whole budget — a slight underestimate vs reality (downhills are
    # priced as flat) but matches how the engine already plans.
    avg_grade = training_ratio_m_per_km / 1000.0
    v_run = predict_uphill_velocity(
        grade=avg_grade,
        v_flat=v_eff,
        k_up=k_up,
        k_terrain=k_terrain,
    )
    km = (v_run * hours * 3600.0) / 1000.0
    elev = km * training_ratio_m_per_km
    return round(km, 1), round(elev, 0)


def effort_for_workout(workout_type: str) -> str:
    """Map an engine workout_type to an effort label for the predictors.

    Anything not explicitly classified falls back to 'easy'.
    """
    if workout_type == 'long_run':
        return 'long_run'
    if workout_type in ('tempo',):
        return 'tempo'
    if workout_type in ('intervals', 'hill_repeats', 'vert_session'):
        # Hard-effort sessions have a similar wall-clock to tempo for the
        # working portion + warmup/cooldown — close enough at this granularity.
        return 'tempo'
    if workout_type == 'descent_session':
        # Eccentric load is high but average velocity is closer to easy
        # (climb portion is moderate, descents are gravity-assisted).
        return 'easy'
    if workout_type == 'race_simulation':
        return 'tempo'
    if workout_type in ('rest', 'strength'):
        return 'easy'  # 0 km anyway — irrelevant
    return 'easy'

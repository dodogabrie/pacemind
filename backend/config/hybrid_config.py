"""Configuration for hybrid prediction system.

Centralizes all constants and hyperparameters for easy tuning.
"""

import logging


# ============================================================================
# TIER THRESHOLDS
# ============================================================================

TIER_2_MIN_ACTIVITIES = 5
"""Minimum activities required for Tier 2 (parameter learning)"""

TIER3_ENABLED = True
"""Tier 3 (personal per-200 m habits on top of Tier 2, services/residual_ml_service.py)
is trained for everyone but USED only for users whose own walk-forward shows it
beats Tier 2 (lower MAPE by > 1 SE, no worse bias, >= 15 held-out runs); the
gate result lives in user_residual_models.metrics. Rebuilt per pred-review #107."""


# ============================================================================
# SEGMENTATION
# ============================================================================

SEGMENT_LENGTH_M = 200
"""Fixed Tier 3 grid (m); also the residual-collection segment length"""


# ============================================================================
# RECENCY WEIGHTING
# ============================================================================

RECENCY_HALF_LIFE_DAYS = 365
"""Half-life for exponential decay of activity recency weights (days)"""


# ============================================================================
# PARAMETER LEARNING (TIER 2)
# ============================================================================

PARAM_BOUNDS = {
    'v_flat': (2.0, 5.0),       # m/s - flat terrain velocity
    'k_up': (0.8, 1.5),          # uphill coefficient
    'k_tech': (0.8, 1.2),        # technical terrain coefficient
    'fatigue_alpha': (0.1, 0.6)  # fatigue accumulation rate
}
"""Parameter bounds (agent safety guardrails)"""

DEFAULT_PARAMS = {
    'v_flat': 3.0,
    'k_up': 1.0,
    'k_tech': 1.0,
    'fatigue_alpha': 0.3,
    'a_param': 3.0,
    'k_terrain_up': 1.08,
    'k_terrain_down': 1.12,
    'k_terrain_flat': 1.05
}
"""Default physics parameters"""


# ============================================================================
# PHYSICS MODEL VERSIONING
# ============================================================================

CURRENT_PHYSICS_MODEL_VERSION = "1.0"
"""Current physics model version for invalidation tracking"""


# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = logging.INFO
"""Default log level for hybrid prediction services"""

LOG_FORMAT = '[%(levelname)s] %(name)s: %(message)s'
"""Log format string"""


def get_logger(name: str) -> logging.Logger:
    """Get configured logger for a module.

    Args:
        name: Module name (use __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    # Only add handler if not already present
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(LOG_LEVEL)
        formatter = logging.Formatter(LOG_FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

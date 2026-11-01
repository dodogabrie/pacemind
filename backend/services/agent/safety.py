"""Safety validation for agent parameter modifications.

Ensures all parameter changes stay within bounds and prevents
excessively large single-step adjustments.
"""

from typing import Dict, Tuple
from config.hybrid_config import PARAM_BOUNDS, DEFAULT_PARAMS


# Maximum change per adjustment as fraction of parameter range
MAX_ADJUSTMENT_FRACTION = 0.30

# Extended bounds for params not in PARAM_BOUNDS (terrain coefficients, a_param)
EXTENDED_BOUNDS = {
    'a_param': (1.0, 6.0),
    'k_terrain_up': (0.9, 1.5),
    'k_terrain_down': (0.9, 1.5),
    'k_terrain_flat': (0.9, 1.3),
}

ALL_BOUNDS = {**PARAM_BOUNDS, **EXTENDED_BOUNDS}


def validate_param_adjustment(
    param_name: str,
    new_value: float,
    current_value: float
) -> Tuple[bool, float, str]:
    """Validate a single parameter adjustment.

    Checks:
    1. Parameter name is recognized
    2. New value is within absolute bounds
    3. Change magnitude doesn't exceed MAX_ADJUSTMENT_FRACTION of range

    Args:
        param_name: Parameter name
        new_value: Proposed new value
        current_value: Current value

    Returns:
        Tuple of (is_valid, clamped_value, message)
    """
    if param_name not in ALL_BOUNDS:
        return False, current_value, f"Unknown parameter: {param_name}"

    low, high = ALL_BOUNDS[param_name]
    param_range = high - low

    # Clamp to absolute bounds
    clamped = max(low, min(high, new_value))

    # Check magnitude limit
    max_delta = param_range * MAX_ADJUSTMENT_FRACTION
    delta = abs(clamped - current_value)

    if delta > max_delta:
        # Clamp the delta instead of rejecting
        direction = 1.0 if clamped > current_value else -1.0
        clamped = current_value + direction * max_delta
        clamped = max(low, min(high, clamped))
        msg = (
            f"{param_name}: change clamped to ±{MAX_ADJUSTMENT_FRACTION:.0%} of range "
            f"({current_value:.4f} → {clamped:.4f}, requested {new_value:.4f})"
        )
        return True, clamped, msg

    if clamped != new_value:
        msg = f"{param_name}: clamped to bounds [{low}, {high}] ({new_value:.4f} → {clamped:.4f})"
        return True, clamped, msg

    return True, clamped, f"{param_name}: {current_value:.4f} → {clamped:.4f}"


def validate_adjustments(
    adjustments: Dict[str, float],
    current_params: Dict[str, float]
) -> Tuple[Dict[str, float], list]:
    """Validate a batch of parameter adjustments.

    Args:
        adjustments: {param_name: new_value} dict
        current_params: Current parameter values

    Returns:
        Tuple of (validated_params, messages)
    """
    validated = {}
    messages = []

    for param_name, new_value in adjustments.items():
        current = current_params.get(param_name)
        if current is None:
            messages.append(f"Parameter {param_name} not found in current params, skipping")
            continue

        is_valid, clamped, msg = validate_param_adjustment(param_name, new_value, current)
        messages.append(msg)

        if is_valid:
            validated[param_name] = clamped

    return validated, messages


def get_param_info() -> Dict:
    """Get parameter metadata for the agent's system prompt.

    Returns:
        Dict with parameter names, bounds, defaults, and descriptions
    """
    descriptions = {
        'v_flat': 'Flat terrain running velocity in m/s. Higher = faster runner on flat ground.',
        'k_up': 'Uphill slowdown coefficient. Higher = relatively faster uphill.',
        'k_tech': 'Technical terrain coefficient. Higher = better on technical/rocky terrain.',
        'fatigue_alpha': 'Fatigue accumulation rate. Higher = fatigues faster over distance.',
        'a_param': 'Downhill power-law exponent. Controls the shape of downhill speed curve.',
        'k_terrain_up': 'Uphill terrain surface factor. Higher = more slowdown on uphill surfaces.',
        'k_terrain_down': 'Downhill terrain surface factor. Higher = more slowdown on downhill surfaces.',
        'k_terrain_flat': 'Flat terrain surface factor. Higher = more slowdown on flat surfaces.',
    }

    return {
        name: {
            'bounds': ALL_BOUNDS.get(name),
            'default': DEFAULT_PARAMS.get(name),
            'description': descriptions.get(name, ''),
        }
        for name in DEFAULT_PARAMS
    }

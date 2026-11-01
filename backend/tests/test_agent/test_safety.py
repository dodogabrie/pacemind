"""Tests for agent safety validation."""

import pytest
from services.agent.safety import (
    validate_param_adjustment,
    validate_adjustments,
    get_param_info,
    ALL_BOUNDS,
    MAX_ADJUSTMENT_FRACTION,
)
from config.hybrid_config import DEFAULT_PARAMS


class TestValidateParamAdjustment:
    """Test individual parameter adjustment validation."""

    def test_valid_adjustment_within_bounds(self):
        """Normal adjustment within bounds should pass."""
        valid, value, msg = validate_param_adjustment('v_flat', 3.2, 3.0)
        assert valid is True
        assert value == 3.2

    def test_clamps_to_upper_bound(self):
        """Value above max should be clamped."""
        valid, value, msg = validate_param_adjustment('v_flat', 10.0, 3.0)
        assert valid is True
        # Should be clamped to max bound or max delta, whichever is stricter
        assert value <= 5.0

    def test_clamps_to_lower_bound(self):
        """Value below min should be clamped."""
        valid, value, msg = validate_param_adjustment('v_flat', 0.5, 3.0)
        assert valid is True
        assert value >= 2.0

    def test_magnitude_limit_enforced(self):
        """Large jumps should be clamped to MAX_ADJUSTMENT_FRACTION of range."""
        # v_flat range is 2.0-5.0 = 3.0, 30% = 0.9
        # From 3.0 to 4.5 is a delta of 1.5 > 0.9
        valid, value, msg = validate_param_adjustment('v_flat', 4.5, 3.0)
        assert valid is True
        max_delta = (5.0 - 2.0) * MAX_ADJUSTMENT_FRACTION
        assert abs(value - 3.0) <= max_delta + 0.001

    def test_unknown_parameter_rejected(self):
        """Unknown parameter names should be rejected."""
        valid, value, msg = validate_param_adjustment('nonexistent', 1.0, 1.0)
        assert valid is False
        assert 'Unknown' in msg

    def test_k_up_within_bounds(self):
        """k_up adjustment within bounds."""
        valid, value, msg = validate_param_adjustment('k_up', 1.1, 1.0)
        assert valid is True
        assert value == 1.1

    def test_fatigue_alpha_bounds(self):
        """fatigue_alpha should respect 0.1-0.6 bounds."""
        valid, value, msg = validate_param_adjustment('fatigue_alpha', 0.05, 0.3)
        assert valid is True
        assert value >= 0.1

    def test_no_change_is_valid(self):
        """Setting same value should be valid."""
        valid, value, msg = validate_param_adjustment('v_flat', 3.0, 3.0)
        assert valid is True
        assert value == 3.0


class TestValidateAdjustments:
    """Test batch parameter validation."""

    def test_multiple_valid_adjustments(self):
        """Multiple valid changes should all pass."""
        adjustments = {'v_flat': 3.2, 'k_up': 1.1}
        validated, messages = validate_adjustments(adjustments, DEFAULT_PARAMS)
        assert 'v_flat' in validated
        assert 'k_up' in validated
        assert len(messages) == 2

    def test_skips_missing_params(self):
        """Params not in current_params should be skipped."""
        adjustments = {'nonexistent_param': 1.0}
        validated, messages = validate_adjustments(adjustments, DEFAULT_PARAMS)
        assert len(validated) == 0
        assert any('not found' in m for m in messages)

    def test_empty_adjustments(self):
        """Empty adjustments dict should return empty results."""
        validated, messages = validate_adjustments({}, DEFAULT_PARAMS)
        assert len(validated) == 0
        assert len(messages) == 0

    def test_mixed_valid_invalid(self):
        """Mix of valid and out-of-bounds should clamp correctly."""
        adjustments = {'v_flat': 3.5, 'k_up': 99.0}
        validated, messages = validate_adjustments(adjustments, DEFAULT_PARAMS)
        assert 'v_flat' in validated
        assert 'k_up' in validated
        assert validated['k_up'] <= 1.5  # Max bound


class TestGetParamInfo:
    """Test parameter info generation."""

    def test_returns_all_default_params(self):
        info = get_param_info()
        for param_name in DEFAULT_PARAMS:
            assert param_name in info
            assert 'bounds' in info[param_name]
            assert 'default' in info[param_name]
            assert 'description' in info[param_name]

    def test_bounds_are_tuples(self):
        info = get_param_info()
        for name, data in info.items():
            if data['bounds'] is not None:
                assert len(data['bounds']) == 2
                assert data['bounds'][0] < data['bounds'][1]

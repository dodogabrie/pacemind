"""Integration tests for the physics prediction pipeline.

Tests the full route prediction from a DataFrame of distance/elevation
to a time prediction, including fatigue accumulation.
"""

import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from services.physics_model.pipeline import run_physics_prediction, DEFAULT_FATIGUE_ALPHA
from services.physics_model.calibration import DEFAULT_PARAMS


def make_flat_route(distance_m=10000, step_m=50):
    """Create a flat route DataFrame."""
    distances = np.arange(0, distance_m, step_m)
    elevations = np.full_like(distances, 500.0, dtype=float)
    return pd.DataFrame({'distance': distances, 'elevation': elevations})


def make_uphill_route(distance_m=5000, step_m=50, grade=0.10, start_elev=500.0):
    """Create a constant-grade uphill route."""
    distances = np.arange(0, distance_m, step_m)
    elevations = start_elev + distances * grade
    return pd.DataFrame({'distance': distances, 'elevation': elevations})


def make_downhill_route(distance_m=5000, step_m=50, grade=-0.10, start_elev=1000.0):
    """Create a constant-grade downhill route."""
    distances = np.arange(0, distance_m, step_m)
    elevations = start_elev + distances * grade
    return pd.DataFrame({'distance': distances, 'elevation': elevations})


def make_up_and_down_route(distance_m=10000, step_m=50, grade=0.10, start_elev=500.0):
    """Create a route that goes up then comes back down."""
    half = distance_m // 2
    d_up = np.arange(0, half, step_m)
    d_down = np.arange(half, distance_m, step_m)
    e_up = start_elev + d_up * grade
    peak_elev = e_up[-1]
    e_down = peak_elev - (d_down - half) * grade
    distances = np.concatenate([d_up, d_down])
    elevations = np.concatenate([e_up, e_down])
    return pd.DataFrame({'distance': distances, 'elevation': elevations})


class TestPredictionPipeline:
    """Test the full prediction pipeline end to end."""

    def test_flat_route_produces_result(self):
        """Pipeline should return valid result for flat route."""
        route = make_flat_route(5000)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        assert 'total_time_seconds' in result
        assert 'segments' in result
        assert result['total_time_seconds'] > 0
        assert len(result['segments']) > 0

    def test_flat_route_time_is_reasonable(self):
        """10km flat at ~5:00/km pace should take ~50 min (3000 sec)."""
        route = make_flat_route(10000)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        # DEFAULT_PARAMS v_flat=3.33 m/s => ~5:00 min/km
        # With terrain factor ~1.05, expect ~5:15/km => ~52 min for 10km
        time_min = result['total_time_seconds'] / 60
        assert 40 < time_min < 65, f"10km flat took {time_min:.1f} min (expected 40-65)"

    def test_uphill_slower_than_flat(self):
        """Same distance uphill should take longer than flat."""
        flat = make_flat_route(5000)
        uphill = make_uphill_route(5000, grade=0.10)

        t_flat = run_physics_prediction(flat, DEFAULT_PARAMS)['total_time_seconds']
        t_up = run_physics_prediction(uphill, DEFAULT_PARAMS)['total_time_seconds']

        assert t_up > t_flat

    def test_downhill_faster_than_flat(self):
        """Same distance downhill should take less time than flat."""
        flat = make_flat_route(5000)
        down = make_downhill_route(5000, grade=-0.05)

        t_flat = run_physics_prediction(flat, DEFAULT_PARAMS)['total_time_seconds']
        t_down = run_physics_prediction(down, DEFAULT_PARAMS)['total_time_seconds']

        assert t_down < t_flat

    def test_steeper_uphill_slower(self):
        """10% uphill should be slower than 5% uphill."""
        up5 = make_uphill_route(5000, grade=0.05)
        up10 = make_uphill_route(5000, grade=0.10)

        t5 = run_physics_prediction(up5, DEFAULT_PARAMS)['total_time_seconds']
        t10 = run_physics_prediction(up10, DEFAULT_PARAMS)['total_time_seconds']

        assert t10 > t5

    def test_segments_have_required_fields(self):
        """Each segment should have distance, length, grade, velocity, pace, time."""
        route = make_flat_route(2000)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        for seg in result['segments']:
            assert 'distance_m' in seg
            assert 'length_m' in seg
            assert 'grade' in seg
            assert 'velocity' in seg
            assert 'pace_min_km' in seg
            assert 'time_s' in seg
            assert 'fatigue_factor' in seg
            assert seg['velocity'] > 0
            assert seg['time_s'] > 0

    def test_total_time_equals_sum_of_segments(self):
        """Total time should equal the sum of individual segment times."""
        route = make_up_and_down_route(10000)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        sum_segments = sum(s['time_s'] for s in result['segments'])
        assert result['total_time_seconds'] == pytest.approx(sum_segments, rel=1e-6)

    def test_fatigue_accumulates_on_descent(self):
        """Fatigue factor should increase after descent segments."""
        route = make_downhill_route(5000, grade=-0.15)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        fatigue_factors = [s['fatigue_factor'] for s in result['segments']]
        # After descent, fatigue should be higher at end than at start
        assert fatigue_factors[-1] >= fatigue_factors[0]

    def test_no_fatigue_on_uphill(self):
        """Fatigue factor should stay at 1.0 on pure uphill (no eccentric load)."""
        route = make_uphill_route(5000, grade=0.10)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        for seg in result['segments']:
            assert seg['fatigue_factor'] == pytest.approx(1.0, abs=0.001)

    def test_zero_fatigue_alpha_disables_fatigue(self):
        """With fatigue_alpha=0, fatigue should have no effect."""
        route = make_downhill_route(5000, grade=-0.15)
        result = run_physics_prediction(route, DEFAULT_PARAMS, fatigue_alpha=0.0)

        for seg in result['segments']:
            assert seg['base_fatigue'] == pytest.approx(1.0, abs=0.001)

    def test_diagnostics_present(self):
        """Result should include diagnostics."""
        route = make_flat_route(5000)
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        assert 'diagnostics' in result
        diag = result['diagnostics']
        assert 'fatigue_alpha' in diag
        assert 'total_distance_km' in diag
        assert diag['total_distance_km'] == pytest.approx(5.0, rel=0.1)

    def test_custom_params_affect_result(self):
        """Different user params should produce different predictions."""
        route = make_flat_route(5000)

        fast_params = {**DEFAULT_PARAMS, 'v_flat': 4.0}  # Fast runner
        slow_params = {**DEFAULT_PARAMS, 'v_flat': 2.5}  # Slow runner

        t_fast = run_physics_prediction(route, fast_params)['total_time_seconds']
        t_slow = run_physics_prediction(route, slow_params)['total_time_seconds']

        assert t_fast < t_slow

    def test_up_and_down_slower_than_flat(self):
        """A route going up then down should be slower than flat (asymmetric cost)."""
        flat = make_flat_route(10000)
        up_down = make_up_and_down_route(10000, grade=0.10)

        t_flat = run_physics_prediction(flat, DEFAULT_PARAMS)['total_time_seconds']
        t_updown = run_physics_prediction(up_down, DEFAULT_PARAMS)['total_time_seconds']

        assert t_updown > t_flat

    def test_ultra_distance_has_extra_fatigue(self):
        """Routes >42km should activate ultra fatigue multiplier."""
        route = make_flat_route(50000)  # 50km
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        # Check that some segments beyond 42km have ultra_multiplier > 1.0
        ultra_segs = [s for s in result['segments'] if s['distance_m'] > 42000]
        assert len(ultra_segs) > 0
        assert any(s['ultra_multiplier'] > 1.0 for s in ultra_segs)

    def test_sub_marathon_no_ultra_fatigue(self):
        """Routes <42km should have ultra_multiplier = 1.0 everywhere."""
        route = make_flat_route(30000)  # 30km
        result = run_physics_prediction(route, DEFAULT_PARAMS)

        for seg in result['segments']:
            assert seg['ultra_multiplier'] == pytest.approx(1.0, abs=0.001)

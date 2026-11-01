"""Unit tests for physics model core functions.

Validates the Minetti cost-of-transport polynomial, velocity predictions,
and fatigue contribution calculations against known biomechanical values.
"""

import sys
import os
import math
import pytest

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from services.physics_model.core import (
    minetti_cost_of_transport,
    normalized_cost_ratio,
    predict_uphill_velocity,
    predict_downhill_velocity,
    calculate_fatigue_contribution,
)


class TestMinettiCostOfTransport:
    """Test the Minetti polynomial against known values from literature."""

    def test_flat_ground_baseline(self):
        """At 0% grade, cost should be 3.6 J/(kg*m) (Minetti 2002 baseline)."""
        cost = minetti_cost_of_transport(0.0)
        assert cost == pytest.approx(3.6, abs=0.01)

    def test_uphill_10_percent(self):
        """At 10% uphill, cost should be significantly higher than flat."""
        cost = minetti_cost_of_transport(0.10)
        assert cost > 3.6  # Must be harder than flat
        assert cost > 5.0  # 10% uphill is substantially harder

    def test_uphill_cost_increases_with_grade(self):
        """Steeper uphill grades should have higher energy cost."""
        costs = [minetti_cost_of_transport(g) for g in [0.0, 0.05, 0.10, 0.15, 0.20]]
        for i in range(len(costs) - 1):
            assert costs[i + 1] > costs[i], f"Cost should increase: grade {(i+1)*5}% ({costs[i+1]}) should be > grade {i*5}% ({costs[i]})"

    def test_gentle_downhill_cheaper_than_flat(self):
        """Gentle downhill (around -10%) should be cheaper than flat (gravity assists)."""
        cost_flat = minetti_cost_of_transport(0.0)
        cost_downhill = minetti_cost_of_transport(-0.10)
        assert cost_downhill < cost_flat

    def test_steep_downhill_cost_increases(self):
        """Very steep downhill should become expensive again (eccentric braking)."""
        cost_gentle = minetti_cost_of_transport(-0.10)
        cost_steep = minetti_cost_of_transport(-0.30)
        assert cost_steep > cost_gentle

    def test_grade_clamping_positive(self):
        """Grades beyond +35% should be clamped (polynomial validity range)."""
        cost_35 = minetti_cost_of_transport(0.35)
        cost_50 = minetti_cost_of_transport(0.50)
        assert cost_35 == pytest.approx(cost_50, abs=0.001)

    def test_grade_clamping_negative(self):
        """Grades beyond -35% should be clamped."""
        cost_neg35 = minetti_cost_of_transport(-0.35)
        cost_neg50 = minetti_cost_of_transport(-0.50)
        assert cost_neg35 == pytest.approx(cost_neg50, abs=0.001)

    def test_cost_is_always_positive(self):
        """Energy cost should never be negative at any grade."""
        for grade_pct in range(-35, 36):
            cost = minetti_cost_of_transport(grade_pct / 100.0)
            assert cost > 0, f"Cost at {grade_pct}% should be positive, got {cost}"

    def test_symmetry_is_broken(self):
        """Uphill and downhill at same magnitude should NOT be symmetric (biology)."""
        cost_up = minetti_cost_of_transport(0.10)
        cost_down = minetti_cost_of_transport(-0.10)
        assert cost_up != pytest.approx(cost_down, abs=0.1)
        assert cost_up > cost_down  # Uphill is harder than downhill at 10%


class TestNormalizedCostRatio:
    """Test the normalized cost ratio function."""

    def test_flat_is_unity(self):
        """Cost ratio at 0% grade should be exactly 1.0."""
        assert normalized_cost_ratio(0.0) == pytest.approx(1.0, abs=0.001)

    def test_uphill_greater_than_one(self):
        """Uphill cost ratio should be > 1.0."""
        assert normalized_cost_ratio(0.10) > 1.0

    def test_gentle_downhill_less_than_one(self):
        """Gentle downhill cost ratio should be < 1.0."""
        assert normalized_cost_ratio(-0.10) < 1.0


class TestPredictUphillVelocity:
    """Test the energy-limited uphill velocity model."""

    def test_flat_returns_near_v_flat(self):
        """On flat ground with no terrain/fatigue penalty, velocity ~ v_flat."""
        v = predict_uphill_velocity(0.0, v_flat=3.5, k_up=1.0, k_terrain=1.0)
        # Cost ratio at 0% is 1.0, so v should be v_flat / (1.0 * 1.0 * 1.0) = 3.5
        assert v == pytest.approx(3.5, abs=0.01)

    def test_uphill_slower_than_flat(self):
        """Uphill should produce lower velocity than flat."""
        v_flat_val = predict_uphill_velocity(0.0, v_flat=3.5, k_up=1.0)
        v_uphill = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0)
        assert v_uphill < v_flat_val

    def test_steeper_grade_slower(self):
        """Steeper uphill should be slower."""
        v_5 = predict_uphill_velocity(0.05, v_flat=3.5, k_up=1.0)
        v_10 = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0)
        v_20 = predict_uphill_velocity(0.20, v_flat=3.5, k_up=1.0)
        assert v_5 > v_10 > v_20

    def test_k_up_greater_than_1_slows_down(self):
        """Higher k_up (weaker climber) should produce slower velocity."""
        v_strong = predict_uphill_velocity(0.10, v_flat=3.5, k_up=0.8)
        v_average = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0)
        v_weak = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.2)
        assert v_strong > v_average > v_weak

    def test_fatigue_slows_down(self):
        """Higher fatigue factor should produce slower velocity."""
        v_fresh = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0, fatigue_factor=1.0)
        v_tired = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0, fatigue_factor=1.3)
        assert v_fresh > v_tired

    def test_terrain_roughness_slows_down(self):
        """Rougher terrain should produce slower velocity."""
        v_road = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0, k_terrain=1.0)
        v_trail = predict_uphill_velocity(0.10, v_flat=3.5, k_up=1.0, k_terrain=1.1)
        assert v_road > v_trail

    def test_velocity_always_positive(self):
        """Velocity should always be positive."""
        for grade_pct in range(0, 36):
            v = predict_uphill_velocity(grade_pct / 100.0, v_flat=3.5, k_up=1.0)
            assert v > 0

    def test_reasonable_pace_range(self):
        """Velocities should produce reasonable paces (3-30 min/km)."""
        for grade_pct in [0, 5, 10, 15, 20, 25, 30]:
            v = predict_uphill_velocity(grade_pct / 100.0, v_flat=3.5, k_up=1.0)
            pace_min_km = (1000 / v) / 60
            assert 3 < pace_min_km < 30, f"Pace at {grade_pct}%: {pace_min_km:.1f} min/km is unreasonable"


class TestPredictDownhillVelocity:
    """Test the kinematic-limited downhill velocity model."""

    def test_continuity_at_zero(self):
        """Downhill model at grade=0 should match uphill model at grade=0."""
        v_up = predict_uphill_velocity(0.0, v_flat=3.5, k_up=1.0, k_terrain=1.08)
        v_down = predict_downhill_velocity(
            0.0, v_flat=3.5, k_tech=1.0, a_param=3.0,
            k_terrain_down=1.12, k_terrain_up=1.08, k_up=1.0
        )
        # At grade 0, downhill should be close to uphill (continuity)
        # Terrain adjustment may cause slight difference: k_terrain_up/k_terrain_down
        assert v_down == pytest.approx(v_up * (1.08 / 1.12), rel=0.05)

    def test_gentle_downhill_faster_than_flat(self):
        """Gentle downhill should be faster than flat."""
        v_flat = predict_uphill_velocity(0.0, v_flat=3.5, k_up=1.0, k_terrain=1.08)
        v_down = predict_downhill_velocity(
            -0.05, v_flat=3.5, k_tech=1.0, a_param=3.0,
            k_terrain_down=1.12, k_terrain_up=1.08, k_up=1.0
        )
        assert v_down > v_flat

    def test_velocity_always_positive(self):
        """Downhill velocity should always be positive."""
        for grade_pct in range(-35, 0):
            v = predict_downhill_velocity(
                grade_pct / 100.0, v_flat=3.5, k_tech=1.0, a_param=3.0,
                k_terrain_down=1.12, k_terrain_up=1.08, k_up=1.0
            )
            assert v > 0

    def test_fatigue_slows_downhill(self):
        """Fatigue should also slow downhill running."""
        v_fresh = predict_downhill_velocity(
            -0.10, v_flat=3.5, k_tech=1.0, a_param=3.0,
            fatigue_factor=1.0, k_up=1.0
        )
        v_tired = predict_downhill_velocity(
            -0.10, v_flat=3.5, k_tech=1.0, a_param=3.0,
            fatigue_factor=1.3, k_up=1.0
        )
        assert v_fresh > v_tired


class TestFatigueContribution:
    """Test eccentric fatigue load calculations."""

    def test_uphill_no_fatigue(self):
        """Uphill segments should contribute zero eccentric load."""
        assert calculate_fatigue_contribution(0.10, 100) == 0.0

    def test_flat_no_fatigue(self):
        """Flat segments should contribute zero eccentric load."""
        assert calculate_fatigue_contribution(0.0, 100) == 0.0

    def test_downhill_has_fatigue(self):
        """Downhill segments should contribute positive eccentric load."""
        load = calculate_fatigue_contribution(-0.10, 100)
        assert load > 0

    def test_steeper_more_fatigue(self):
        """Steeper descent should cause more eccentric load."""
        load_5 = calculate_fatigue_contribution(-0.05, 100)
        load_10 = calculate_fatigue_contribution(-0.10, 100)
        load_20 = calculate_fatigue_contribution(-0.20, 100)
        assert load_5 < load_10 < load_20

    def test_longer_segment_more_fatigue(self):
        """Longer segments should accumulate more fatigue."""
        load_short = calculate_fatigue_contribution(-0.10, 50)
        load_long = calculate_fatigue_contribution(-0.10, 200)
        assert load_long > load_short

    def test_proportional_to_distance(self):
        """Fatigue should be proportional to distance."""
        load_100 = calculate_fatigue_contribution(-0.10, 100)
        load_200 = calculate_fatigue_contribution(-0.10, 200)
        assert load_200 == pytest.approx(2 * load_100, rel=0.001)

    def test_very_gentle_descent_minimal(self):
        """Very gentle descent (<0.5%) should have minimal or zero contribution."""
        load = calculate_fatigue_contribution(-0.003, 100)
        assert load == pytest.approx(0.0, abs=0.01)

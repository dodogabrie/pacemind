"""Tests for VDOT (Daniels) and Riegel pace-zone derivation."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.vdot_service import (
    vdot_from_race, vdot_zones, riegel_predict_time, riegel_flat_pace,
    RIEGEL_EXPONENT,
)
from services.pace_zone_service import compute_zones_by_method, ZONE_ORDER


class TestVdotFromRace:
    def test_5k_20min_is_about_50(self):
        # Daniels' tables put a 20:00 5K at VDOT ~49.8.
        vdot = vdot_from_race(5000, 20 * 60)
        assert vdot == pytest.approx(49.8, abs=1.0)

    def test_10k_40min_is_about_50(self):
        vdot = vdot_from_race(10000, 40 * 60)
        assert vdot == pytest.approx(51.0, abs=2.0)

    def test_faster_race_higher_vdot(self):
        assert vdot_from_race(5000, 18 * 60) > vdot_from_race(5000, 22 * 60)

    def test_non_positive_raises(self):
        with pytest.raises(ValueError):
            vdot_from_race(0, 1200)
        with pytest.raises(ValueError):
            vdot_from_race(5000, 0)


class TestVdotZones:
    def test_five_zones_present_and_ordered(self):
        zones = vdot_zones(50.0)
        assert set(zones) == set(ZONE_ORDER)
        for z in zones.values():
            assert z['min_pace'] <= z['max_pace']

    def test_zone_speed_ordering(self):
        zones = vdot_zones(50.0)
        # Recovery slowest (largest pace), interval fastest (smallest).
        assert zones['recovery']['min_pace'] > zones['easy']['min_pace']
        assert zones['easy']['min_pace'] > zones['tempo']['min_pace']
        assert zones['tempo']['min_pace'] > zones['threshold']['min_pace']
        assert zones['threshold']['min_pace'] > zones['interval']['min_pace']

    def test_threshold_pace_for_vdot_50(self):
        # Daniels' T pace for VDOT 50 is ~4:15/km (4.25), mid threshold band.
        zones = vdot_zones(50.0)
        assert zones['threshold']['min_pace'] <= 4.25 <= zones['threshold']['max_pace']


class TestRiegel:
    def test_known_projection_doubling_distance(self):
        # 10K in 40:00 -> 20K should be 40min * 2^1.06.
        t = riegel_predict_time(10000, 2400, 20000)
        assert t == pytest.approx(2400 * 2 ** RIEGEL_EXPONENT, rel=1e-6)

    def test_longer_distance_slower_pace(self):
        # Marathon pace from a 10K is slower than the 10K pace.
        flat = riegel_flat_pace(10000, 40 * 60)  # min/km at marathon
        ten_k_pace = (40 * 60 / 60) / 10
        assert flat > ten_k_pace

    def test_non_positive_raises(self):
        with pytest.raises(ValueError):
            riegel_predict_time(0, 100, 200)


class TestDispatcher:
    def test_physics_default(self):
        result = compute_zones_by_method('physics', v_flat_ms=3.33)
        assert result['method'] == 'physics'
        assert set(result['zones']) == set(ZONE_ORDER)

    def test_vdot_with_race(self):
        result = compute_zones_by_method(
            'vdot', v_flat_ms=3.33, race_distance_m=5000, race_time_s=1200)
        assert result['method'] == 'vdot'
        assert 'vdot' in result['meta']

    def test_riegel_with_race(self):
        result = compute_zones_by_method(
            'riegel', v_flat_ms=3.33, race_distance_m=10000, race_time_s=2400)
        assert result['method'] == 'riegel'
        assert 'riegel_flat_pace' in result['meta']

    def test_vdot_without_race_falls_back_to_physics(self):
        result = compute_zones_by_method('vdot', v_flat_ms=3.33)
        assert result['method'] == 'physics'

    def test_unknown_method_falls_back_to_physics(self):
        result = compute_zones_by_method('bogus', v_flat_ms=3.33)
        assert result['method'] == 'physics'

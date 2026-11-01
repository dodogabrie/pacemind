"""Tests for the pace zone service."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.pace_zone_service import (
    compute_default_zones, flat_speed_to_pace, merge_zone_overrides,
    format_pace, resolve_pace_target, ZONE_ORDER,
    compute_hr_zones, estimate_hr_max_from_streams,
    compute_power_zones, estimate_ftp_from_streams,
)


class TestFlatSpeedToPace:
    def test_typical_speed(self):
        # 3.33 m/s = ~5:00/km
        pace = flat_speed_to_pace(3.33)
        assert abs(pace - 5.0) < 0.05

    def test_fast_speed(self):
        # 5.0 m/s = ~3:20/km
        pace = flat_speed_to_pace(5.0)
        assert abs(pace - 3.33) < 0.05

    def test_zero_speed(self):
        pace = flat_speed_to_pace(0)
        assert pace == 6.0  # fallback


class TestComputeDefaultZones:
    def test_five_zones(self):
        zones = compute_default_zones(5.0)
        assert len(zones) == 5
        for name in ZONE_ORDER:
            assert name in zones
            z = zones[name]
            assert 'min_pace' in z
            assert 'max_pace' in z
            assert z['min_pace'] <= z['max_pace']

    def test_zone_ordering(self):
        """Recovery should be slowest, interval fastest."""
        zones = compute_default_zones(5.0)
        assert zones['recovery']['min_pace'] > zones['easy']['min_pace']
        assert zones['easy']['min_pace'] > zones['tempo']['min_pace']
        assert zones['tempo']['min_pace'] > zones['threshold']['min_pace']
        assert zones['threshold']['min_pace'] > zones['interval']['min_pace']

    def test_relative_to_flat_pace(self):
        zones = compute_default_zones(5.0)
        # Tempo should be around flat pace (0.92-1.0x)
        assert zones['tempo']['min_pace'] == pytest.approx(4.6, abs=0.01)
        assert zones['tempo']['max_pace'] == pytest.approx(5.0, abs=0.01)


class TestMergeZoneOverrides:
    def test_no_overrides(self):
        defaults = compute_default_zones(5.0)
        merged = merge_zone_overrides(defaults, None)
        assert merged == defaults

    def test_partial_override(self):
        defaults = compute_default_zones(5.0)
        overrides = {'tempo': {'min_pace': 4.5, 'max_pace': 4.8}}
        merged = merge_zone_overrides(defaults, overrides)
        assert merged['tempo']['min_pace'] == 4.5
        assert merged['tempo']['max_pace'] == 4.8
        # Other zones unchanged
        assert merged['easy'] == defaults['easy']

    def test_single_field_override(self):
        defaults = compute_default_zones(5.0)
        overrides = {'easy': {'min_pace': 5.2}}
        merged = merge_zone_overrides(defaults, overrides)
        assert merged['easy']['min_pace'] == 5.2
        assert merged['easy']['max_pace'] == defaults['easy']['max_pace']


class TestFormatPace:
    def test_exact_minutes(self):
        assert format_pace(5.0) == "5:00"

    def test_with_seconds(self):
        assert format_pace(4.5) == "4:30"

    def test_under_four(self):
        assert format_pace(3.75) == "3:45"


class TestResolvePaceTarget:
    def test_resolve_known_zone(self):
        zones = compute_default_zones(5.0)
        result = resolve_pace_target('tempo', zones)
        assert result is not None
        assert 'display' in result
        assert '/km' in result['display']

    def test_resolve_unknown_zone(self):
        zones = compute_default_zones(5.0)
        result = resolve_pace_target('ultrafast', zones)
        assert result is None


class TestComputeHrZones:
    def test_none_without_anchors(self):
        assert compute_hr_zones() is None
        assert compute_hr_zones(hr_rest=50) is None  # rest alone is useless

    def test_karvonen_when_max_and_rest(self):
        result = compute_hr_zones(hr_max=190, hr_rest=50)
        assert result['basis'] == 'karvonen'
        # HRR = 140. easy band 0.60-0.70 -> 50+84=134, 50+98=148.
        easy = result['zones']['easy']
        assert easy['min_bpm'] == 134
        assert easy['max_bpm'] == 148

    def test_pct_hr_max_fallback(self):
        result = compute_hr_zones(hr_max=200)
        assert result['basis'] == 'pct_hr_max'
        # easy 0.70-0.80 of 200 -> 140-160
        assert result['zones']['easy']['min_bpm'] == 140
        assert result['zones']['easy']['max_bpm'] == 160

    def test_lthr_takes_priority(self):
        result = compute_hr_zones(hr_max=190, hr_rest=50, lthr=170)
        assert result['basis'] == 'lthr'
        # threshold 0.95-1.00 of 170 -> 162-170 (capped at hr_max=190, no clip)
        assert result['zones']['threshold']['max_bpm'] == 170

    def test_all_five_zones_and_ordering(self):
        result = compute_hr_zones(hr_max=190, hr_rest=50)
        zones = result['zones']
        assert len(zones) == 5
        # HR rises with intensity: recovery lowest, interval highest.
        assert zones['recovery']['max_bpm'] <= zones['easy']['max_bpm']
        assert zones['easy']['max_bpm'] <= zones['tempo']['max_bpm']
        assert zones['tempo']['max_bpm'] <= zones['threshold']['max_bpm']
        assert zones['threshold']['max_bpm'] <= zones['interval']['max_bpm']
        for z in zones.values():
            assert z['min_bpm'] <= z['max_bpm']

    def test_capped_at_hr_max(self):
        # lthr interval band exceeds 1.0 -> would surpass hr_max; must be capped.
        result = compute_hr_zones(hr_max=175, lthr=170)
        assert result['zones']['interval']['max_bpm'] <= 175

    def test_invalid_rest_above_max_falls_back_to_pct(self):
        result = compute_hr_zones(hr_max=180, hr_rest=185)
        assert result['basis'] == 'pct_hr_max'


class TestComputePowerZones:
    def test_none_without_ftp(self):
        assert compute_power_zones() is None
        assert compute_power_zones(0) is None
        assert compute_power_zones(None) is None

    def test_five_zones_from_ftp(self):
        result = compute_power_zones(250)
        assert result['inputs']['ftp_w'] == 250
        zones = result['zones']
        assert len(zones) == 5
        for name in ZONE_ORDER:
            assert name in zones
            assert zones[name]['min_w'] <= zones[name]['max_w']

    def test_band_boundaries(self):
        # FTP 200 W. tempo 0.90-1.00 -> 180-200; threshold 1.00-1.15 -> 200-230.
        zones = compute_power_zones(200)['zones']
        assert zones['tempo']['min_w'] == 180
        assert zones['tempo']['max_w'] == 200
        assert zones['threshold']['min_w'] == 200
        assert zones['threshold']['max_w'] == 230

    def test_power_rises_with_intensity(self):
        zones = compute_power_zones(250)['zones']
        assert zones['recovery']['max_w'] <= zones['easy']['max_w']
        assert zones['easy']['max_w'] <= zones['tempo']['max_w']
        assert zones['tempo']['max_w'] <= zones['threshold']['max_w']
        assert zones['threshold']['max_w'] <= zones['interval']['max_w']

    def test_coerces_float_ftp(self):
        assert compute_power_zones(250.0)['inputs']['ftp_w'] == 250


class TestEstimateFtpFromStreams:
    def test_no_data(self):
        assert estimate_ftp_from_streams([]) is None
        assert estimate_ftp_from_streams([{'distance': [1, 2]}]) is None

    def test_requires_full_window(self):
        # Only 100 s of data — far short of the 20-min window.
        streams = [{'watts': [200] * 100, 'time': list(range(100))}]
        assert estimate_ftp_from_streams(streams) is None

    def test_constant_power_over_window(self):
        # 25 min of constant 200 W: best 20-min avg = 200, ×0.95 = 190.
        n = 1500
        streams = [{'watts': [200] * n, 'time': list(range(n))}]
        assert estimate_ftp_from_streams(streams) == 190

    def test_picks_best_window_across_activities(self):
        n = 1500
        low = {'watts': [150] * n, 'time': list(range(n))}
        high = {'watts': [220] * n, 'time': list(range(n))}
        # best 20-min avg = 220, ×0.95 = 209.
        assert estimate_ftp_from_streams([low, high]) == 209

    def test_assumes_1hz_when_time_missing(self):
        n = 1500
        streams = [{'watts': [180] * n}]
        # 180 ×0.95 = 171.
        assert estimate_ftp_from_streams(streams) == 171

    def test_ignores_non_dict(self):
        n = 1500
        streams = [None, 5, {'watts': [200] * n, 'time': list(range(n))}]
        assert estimate_ftp_from_streams(streams) == 190


class TestEstimateHrMaxFromStreams:
    def test_no_data(self):
        assert estimate_hr_max_from_streams([]) is None
        assert estimate_hr_max_from_streams([{'distance': [1, 2]}]) is None

    def test_global_max_times_multiplier(self):
        streams = [
            {'heartrate': [120, 150, 160]},
            {'heartrate': [140, 178, 100]},
        ]
        # max valid sample 178 * 1.02 = 181.56 -> 182
        assert estimate_hr_max_from_streams(streams) == 182

    def test_filters_artefacts(self):
        streams = [{'heartrate': [0, -5, 250, 300, 165]}]
        # only 165 is valid -> 165 * 1.02 = 168.3 -> 168
        assert estimate_hr_max_from_streams(streams) == 168

    def test_ignores_non_dict(self):
        assert estimate_hr_max_from_streams([None, 5, {'heartrate': [170]}]) == 173

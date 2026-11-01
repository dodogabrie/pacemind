"""Tests for the workout service (structured steps validation and summaries)."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.workout_service import validate_steps, compute_step_summaries, steps_to_text


class TestValidateSteps:
    def test_valid_simple_steps(self):
        steps = [
            {"type": "warmup", "duration_min": 15, "target": {"type": "effort", "rpe": 3}},
            {"type": "work", "duration_min": 20, "target": {"type": "effort", "rpe": 7}},
            {"type": "cooldown", "duration_min": 10, "target": {"type": "effort", "rpe": 2}},
        ]
        valid, err = validate_steps(steps)
        assert valid is True
        assert err is None

    def test_valid_repeat_steps(self):
        steps = [
            {"type": "warmup", "duration_min": 15, "target": {"type": "effort", "rpe": 3}},
            {
                "type": "repeat", "repeats": 6,
                "steps": [
                    {"type": "work", "elevation_gain_m": 50, "target": {"type": "effort", "rpe": 8}},
                    {"type": "rest", "duration_min": 3, "target": {"type": "effort", "rpe": 3}},
                ]
            },
            {"type": "cooldown", "duration_min": 10, "target": {"type": "effort", "rpe": 2}},
        ]
        valid, err = validate_steps(steps)
        assert valid is True

    def test_valid_pace_target(self):
        steps = [
            {"type": "work", "duration_min": 10, "target": {"type": "pace", "zone": "tempo"}},
        ]
        valid, err = validate_steps(steps)
        assert valid is True

    def test_valid_distance_step(self):
        steps = [
            {"type": "work", "distance_m": 1000, "target": {"type": "hr", "zone": 4}},
        ]
        valid, err = validate_steps(steps)
        assert valid is True

    def test_invalid_empty_list(self):
        valid, err = validate_steps([])
        assert valid is False
        assert 'empty' in err

    def test_invalid_not_list(self):
        valid, err = validate_steps("not a list")
        assert valid is False

    def test_invalid_step_type(self):
        steps = [{"type": "sprint", "duration_min": 5}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'invalid type' in err

    def test_invalid_no_measure(self):
        steps = [{"type": "work", "target": {"type": "effort", "rpe": 5}}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'duration_min' in err

    def test_invalid_nested_repeat(self):
        steps = [{
            "type": "repeat", "repeats": 3,
            "steps": [{
                "type": "repeat", "repeats": 2,
                "steps": [{"type": "work", "duration_min": 5}]
            }]
        }]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'nested' in err

    def test_invalid_rpe_out_of_range(self):
        steps = [{"type": "work", "duration_min": 5, "target": {"type": "effort", "rpe": 15}}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'RPE' in err

    def test_invalid_hr_zone(self):
        steps = [{"type": "work", "duration_min": 5, "target": {"type": "hr", "zone": 7}}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'HR zone' in err

    def test_invalid_target_type(self):
        steps = [{"type": "work", "duration_min": 5, "target": {"type": "cadence"}}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'target type' in err

    def test_power_target_zone_out_of_range(self):
        steps = [{"type": "work", "duration_min": 5, "target": {"type": "power", "zone": 6}}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'power zone' in err

    def test_repeat_no_children(self):
        steps = [{"type": "repeat", "repeats": 3, "steps": []}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'child steps' in err

    def test_repeat_too_many(self):
        steps = [{"type": "repeat", "repeats": 50, "steps": [{"type": "work", "duration_min": 1}]}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'repeats' in err

    def test_valid_terrain(self):
        steps = [{"type": "work", "duration_min": 10, "terrain": "trail"}]
        valid, err = validate_steps(steps)
        assert valid is True

    def test_invalid_terrain(self):
        steps = [{"type": "work", "duration_min": 10, "terrain": "water"}]
        valid, err = validate_steps(steps)
        assert valid is False
        assert 'terrain' in err

    def test_open_target(self):
        steps = [{"type": "work", "duration_min": 10, "target": {"type": "open"}}]
        valid, err = validate_steps(steps)
        assert valid is True


class TestComputeStepSummaries:
    def test_simple_duration(self):
        steps = [
            {"type": "warmup", "duration_min": 15},
            {"type": "work", "duration_min": 30},
            {"type": "cooldown", "duration_min": 10},
        ]
        result = compute_step_summaries(steps)
        assert result['duration_min'] == 55
        assert result['step_count'] == 3

    def test_distance_steps(self):
        steps = [
            {"type": "work", "distance_m": 1000},
            {"type": "work", "distance_m": 2000},
        ]
        result = compute_step_summaries(steps)
        assert result['distance_km'] == 3.0

    def test_repeat_multiplier(self):
        steps = [
            {"type": "warmup", "duration_min": 10},
            {
                "type": "repeat", "repeats": 5,
                "steps": [
                    {"type": "work", "duration_min": 3, "distance_m": 400},
                    {"type": "rest", "duration_min": 2},
                ]
            },
        ]
        result = compute_step_summaries(steps)
        assert result['duration_min'] == 10 + 5 * (3 + 2)  # 35
        assert result['distance_km'] == 2.0  # 5 * 400m
        assert result['step_count'] == 1 + 5 * 2  # 11

    def test_elevation_steps(self):
        steps = [
            {"type": "repeat", "repeats": 6, "steps": [
                {"type": "work", "elevation_gain_m": 50},
                {"type": "rest", "duration_min": 3},
            ]},
        ]
        result = compute_step_summaries(steps)
        assert result['elevation_m'] == 300  # 6 * 50

    def test_empty_steps(self):
        result = compute_step_summaries([])
        assert result['distance_km'] is None
        assert result['duration_min'] is None
        assert result['step_count'] == 0


class TestStepsToText:
    def test_simple_steps(self):
        steps = [
            {"type": "warmup", "duration_min": 15, "target": {"type": "effort", "rpe": 3}},
            {"type": "work", "duration_min": 20, "target": {"type": "pace", "zone": "tempo"}},
            {"type": "cooldown", "duration_min": 10},
        ]
        text = steps_to_text(steps)
        assert "Warmup" in text
        assert "15min" in text
        assert "RPE 3" in text
        assert "Run" in text
        assert "@ tempo" in text
        assert "Cooldown" in text

    def test_repeat_rendering(self):
        steps = [
            {"type": "repeat", "repeats": 4, "steps": [
                {"type": "work", "elevation_gain_m": 50, "target": {"type": "effort", "rpe": 8}},
                {"type": "rest", "duration_min": 3},
            ]},
        ]
        text = steps_to_text(steps)
        assert "4x:" in text
        assert "+50m" in text
        assert "RPE 8" in text

    def test_distance_formatting(self):
        steps = [
            {"type": "work", "distance_m": 400},
            {"type": "work", "distance_m": 2000},
        ]
        text = steps_to_text(steps)
        assert "400m" in text
        assert "2km" in text

    def test_notes_in_text(self):
        steps = [
            {"type": "work", "duration_min": 10, "notes": "push hard"},
        ]
        text = steps_to_text(steps)
        assert "# push hard" in text

    def test_hr_target_without_zones_renders_bare_label(self):
        steps = [{"type": "work", "duration_min": 20, "target": {"type": "hr", "zone": 2}}]
        assert "Z2" in steps_to_text(steps)
        assert "bpm" not in steps_to_text(steps)

    def test_hr_target_with_zones_renders_bpm(self):
        hr_zones = {
            'recovery':  {'min_bpm': 110, 'max_bpm': 120},
            'easy':      {'min_bpm': 120, 'max_bpm': 135},
            'tempo':     {'min_bpm': 150, 'max_bpm': 160},
            'threshold': {'min_bpm': 160, 'max_bpm': 170},
            'interval':  {'min_bpm': 170, 'max_bpm': 180},
        }
        steps = [{"type": "work", "duration_min": 20, "target": {"type": "hr", "zone": 2}}]
        text = steps_to_text(steps, hr_zones=hr_zones)
        assert "Z2 (120-135 bpm)" in text

    def test_hr_zones_thread_into_repeats(self):
        hr_zones = {'interval': {'min_bpm': 170, 'max_bpm': 180}}
        steps = [{"type": "repeat", "repeats": 3, "steps": [
            {"type": "work", "distance_m": 400, "target": {"type": "hr", "zone": 5}},
        ]}]
        text = steps_to_text(steps, hr_zones=hr_zones)
        assert "Z5 (170-180 bpm)" in text

    def test_power_target_without_zones_renders_bare_label(self):
        steps = [{"type": "work", "duration_min": 20, "target": {"type": "power", "zone": 3}}]
        assert "Z3" in steps_to_text(steps)
        assert "W" not in steps_to_text(steps)

    def test_power_target_with_zones_renders_watts(self):
        power_zones = {
            'recovery':  {'min_w': 100, 'max_w': 160},
            'easy':      {'min_w': 160, 'max_w': 180},
            'tempo':     {'min_w': 180, 'max_w': 200},
            'threshold': {'min_w': 200, 'max_w': 230},
            'interval':  {'min_w': 230, 'max_w': 300},
        }
        steps = [{"type": "work", "duration_min": 20, "target": {"type": "power", "zone": 3}}]
        text = steps_to_text(steps, power_zones=power_zones)
        assert "Z3 (180-200 W)" in text

    def test_power_zones_thread_into_repeats(self):
        power_zones = {'interval': {'min_w': 230, 'max_w': 300}}
        steps = [{"type": "repeat", "repeats": 3, "steps": [
            {"type": "work", "distance_m": 400, "target": {"type": "power", "zone": 5}},
        ]}]
        text = steps_to_text(steps, power_zones=power_zones)
        assert "Z5 (230-300 W)" in text


class TestTextToSteps:
    def test_basic_round_trip(self):
        from services.workout_service import text_to_steps, steps_to_text
        text = (
            "Warmup 15min Z2 on road\n"
            "4x:\n"
            "  1km +80m @ 4:30/km on trail\n"
            "  Recovery 3min Z1\n"
            "Run 20min Z3\n"
            "Cooldown 10min RPE 2\n"
        )
        steps, errors = text_to_steps(text)
        assert errors == []
        assert len(steps) == 4
        assert steps[0]['type'] == 'warmup'
        assert steps[0]['duration_min'] == 15
        assert steps[0]['target'] == {'type': 'hr', 'zone': 2}
        assert steps[0]['terrain'] == 'road'
        assert steps[1]['type'] == 'repeat'
        assert steps[1]['repeats'] == 4
        rep_kids = steps[1]['steps']
        assert len(rep_kids) == 2
        assert rep_kids[0]['distance_m'] == 1000
        assert rep_kids[0]['elevation_gain_m'] == 80
        assert rep_kids[0]['elevation_direction'] == 'up'  # positional default inside repeat
        assert rep_kids[0]['target'] == {'type': 'pace', 'zone': '4:30/km'}
        assert rep_kids[0]['terrain'] == 'trail'
        assert rep_kids[1]['type'] == 'rest'
        assert steps[2]['type'] == 'work'
        assert steps[3]['type'] == 'cooldown'
        # Round-trip should re-parse to identical structure
        re_steps, _ = text_to_steps(steps_to_text(steps))
        assert re_steps == steps

    def test_top_level_elevation_default_round_trip(self):
        # Bare "Xm" is distance; elevation requires an explicit sign or D+ suffix.
        # With no sign at top level, +-200m means round-trip; users can also write
        # the suffix form "200m D+-".
        from services.workout_service import text_to_steps
        steps, errors = text_to_steps("Run 10km 200m D+-\n")
        assert errors == []
        assert len(steps) == 1
        assert steps[0]['distance_m'] == 10000
        assert steps[0]['elevation_gain_m'] == 200
        assert steps[0]['elevation_direction'] == 'round_trip'

    def test_explicit_signs(self):
        from services.workout_service import text_to_steps
        steps, _ = text_to_steps("Run 5km +100m\nRun 5km -100m\nRun 5km +-100m\n")
        assert steps[0]['elevation_direction'] == 'up'
        assert steps[1]['elevation_direction'] == 'down'
        assert steps[2]['elevation_direction'] == 'round_trip'

    def test_italian_keywords(self):
        from services.workout_service import text_to_steps
        steps, errors = text_to_steps("Riscaldamento 10min Z2\nRecupero 5min\nDefaticamento 10min\n")
        assert errors == []
        assert [s['type'] for s in steps] == ['warmup', 'rest', 'cooldown']

    def test_predict_duration_round_trip(self):
        from services.workout_service import text_to_steps, predict_steps_durations
        steps, _ = text_to_steps("Run 10km 200m\n")
        # No params -> defaults (5:00/km flat). 10km round-trip with 200m gain
        # should be slower than flat (~50min); sanity-check it falls in 50..90 min.
        out = predict_steps_durations(steps, params=None)
        assert out[0].get('duration_predicted') is True
        assert 45 < out[0]['duration_min'] < 90

    def test_predict_duration_uphill_only(self):
        from services.workout_service import text_to_steps, predict_steps_durations
        steps, _ = text_to_steps("4x:\n  1km +100m\n  Recovery 2min\n")
        out = predict_steps_durations(steps, params=None)
        rep_kids = out[0]['steps']
        # 1km at 10% uphill should be ~9-12 min
        assert 7 < rep_kids[0]['duration_min'] < 15
        assert rep_kids[0].get('duration_predicted') is True
        # Recovery already had explicit duration -> not flagged predicted
        assert rep_kids[1]['duration_min'] == 2
        assert 'duration_predicted' not in rep_kids[1]

    def test_explicit_duration_preserved(self):
        from services.workout_service import text_to_steps, predict_steps_durations
        steps, _ = text_to_steps("Run 5km 30min\n")
        out = predict_steps_durations(steps, params=None)
        assert out[0]['duration_min'] == 30
        assert 'duration_predicted' not in out[0]

    def test_invalid_line_recorded_in_errors(self):
        from services.workout_service import text_to_steps
        steps, errors = text_to_steps("Run\n")
        assert steps == []
        assert len(errors) == 1
        assert errors[0]['line'] == 1

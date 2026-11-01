"""intervals.icu export: workout syntax and event dates."""

from datetime import datetime
from types import SimpleNamespace

from services.calendar_export_service import plan_to_icu_events, steps_to_icu


def test_steps_to_icu_syntax():
    steps = [
        {'type': 'warmup', 'duration_min': 15, 'target': {'type': 'hr', 'zone': 2}},
        {'type': 'repeat', 'repeats': 5, 'steps': [
            {'type': 'work', 'distance_m': 1000, 'target': {'type': 'pace', 'zone': '4:00/km'}},
            {'type': 'rest', 'duration_min': 0.5},
        ]},
        {'type': 'cooldown', 'duration_min': 10, 'target': {'type': 'hr', 'zone': 1}},
    ]
    assert steps_to_icu(steps) == (
        'Warmup\n- 15m Z2 HR\n\n'
        '5x\n- 1km 4:00/km Pace\n- 30s\n\n'
        'Cooldown\n- 10m Z1 HR'
    )


def test_plan_events_dates_and_rest_skipped():
    plan = SimpleNamespace(id=7, created_at=datetime(2026, 10, 22), weeks=[
        {'week_number': 2, 'days': [
            {'day': 'Monday', 'workout_type': 'rest'},
            {'day': 'Wednesday', 'workout_type': 'easy', 'duration_min': 50, 'title': 'Easy'},
        ]},
    ])
    [ev] = plan_to_icu_events(plan)
    assert ev['start_date_local'] == '2026-10-28T00:00:00'  # week 2 of the plan started Mon 19 Oct
    assert ev['moving_time'] == 3000
    assert ev['description'] == '- 50m Z2 HR'
    assert ev['external_id'] == 'pacemind-7-w2-Wednesday'


def test_saved_day_dates_win_over_created_at_and_race_has_no_z2_step():
    # Plan created on a Saturday for the following Monday: the stored dates
    # (anchored to the race) must be used, not the created-at Monday.
    plan = SimpleNamespace(id=2, created_at=datetime(2026, 10, 24), weeks=[
        {'week_number': 15, 'days': [
            {'day': 'Sunday', 'date': '2027-02-07', 'workout_type': 'race_simulation',
             'distance_km': 34, 'title': 'GARA', 'notes': 'Partenza 9:30'},
        ]},
    ])
    [ev] = plan_to_icu_events(plan)
    assert ev['start_date_local'] == '2027-02-07T00:00:00'
    assert ev['description'] == 'Partenza 9:30'

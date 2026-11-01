"""Structured warnings emitted by validate_plan_feasibility."""

from services import plan_engine


def _build_week(week_no, weekly_km, days):
    return {
        'week_number': week_no,
        'theme': 'Test',
        'total_km': weekly_km,
        'total_elevation_m': sum(d.get('elevation_m', 0) for d in days),
        'start_date': '2026-09-01',
        'days': days,
    }


def _day(day, wt='easy', km=8, elev=20, **extra):
    return {
        'day': day,
        'date': '2026-09-01',
        'workout_type': wt,
        'title': 'x',
        'distance_km': km,
        'elevation_m': elev,
        'intensity': 'easy',
        'notes': '',
        'route_id': None,
        'route_match_quality': 'pending',
        'suggested_alternatives': [],
        **extra,
    }


def test_clean_plan_emits_no_warnings():
    weeks = [_build_week(1, 30, [
        _day('Monday'), _day('Tuesday'), _day('Wednesday'),
        _day('Thursday'), _day('Friday', wt='rest', km=0, elev=0),
        _day('Saturday'), _day('Sunday', wt='long_run', km=15, elev=300),
    ])]
    prefs = {'max_weekly_km': 50, 'max_long_run_km': 25, 'terrain_profile': 'rolling_hills'}
    warns = plan_engine.validate_plan_feasibility(
        weeks, prefs, 'rolling_hills',
        race_distance_km=20, race_elevation_m=400,
    )
    assert warns == []


def test_volume_above_cap_warning():
    weeks = [_build_week(1, 80, [_day('Monday', km=80)])]
    prefs = {'max_weekly_km': 50, 'terrain_profile': 'rolling_hills'}
    warns = plan_engine.validate_plan_feasibility(weeks, prefs, 'rolling_hills')
    issues = [w['issue'] for w in warns]
    assert 'volume_above_cap' in issues


def test_long_run_above_cap_warning():
    weeks = [_build_week(1, 30, [
        _day('Sunday', wt='long_run', km=30, elev=400),
    ])]
    prefs = {'max_weekly_km': 50, 'max_long_run_km': 20, 'terrain_profile': 'rolling_hills'}
    warns = plan_engine.validate_plan_feasibility(weeks, prefs, 'rolling_hills')
    assert any(w['issue'] == 'long_run_above_cap' for w in warns)


def test_midweek_elev_too_high_for_flat_urban():
    weeks = [_build_week(1, 20, [
        _day('Tuesday', wt='hill_repeats', km=10, elev=400),
    ])]
    prefs = {'max_weekly_km': 50, 'terrain_profile': 'flat_urban'}
    warns = plan_engine.validate_plan_feasibility(weeks, prefs, 'flat_urban')
    assert any(w['issue'] == 'midweek_elev_too_high' for w in warns)


def test_unmatched_route_emits_info_warning():
    weeks = [_build_week(1, 20, [
        _day('Saturday', wt='long_run', km=18, elev=400, route_match_quality='unmatched'),
    ])]
    warns = plan_engine.validate_plan_feasibility(weeks, {}, None)
    info = [w for w in warns if w['issue'] == 'unmatched_route']
    assert len(info) == 1
    assert info[0]['severity'] == 'info'


def test_race_terrain_mismatch_critical():
    """30 m/km is the threshold — 35 m/km should trigger; 25 should not."""
    weeks = [_build_week(1, 20, [_day('Sunday', wt='long_run', km=15, elev=200)])]
    prefs = {'max_weekly_km': 50, 'terrain_profile': 'flat_urban'}
    warns = plan_engine.validate_plan_feasibility(
        weeks, prefs, 'flat_urban',
        race_distance_km=20, race_elevation_m=700,  # 35 m/km
    )
    crits = [w for w in warns if w['severity'] == 'critical']
    assert len(crits) == 1
    assert crits[0]['issue'] == 'race_terrain_mismatch'

    warns2 = plan_engine.validate_plan_feasibility(
        weeks, prefs, 'flat_urban',
        race_distance_km=20, race_elevation_m=400,  # 20 m/km
    )
    assert not any(w['severity'] == 'critical' for w in warns2)


def test_volume_jump_warning():
    weeks = [
        _build_week(1, 30, [_day('Monday', km=30)]),
        _build_week(2, 60, [_day('Monday', km=60)]),  # 100% increase
    ]
    warns = plan_engine.validate_plan_feasibility(weeks, {}, None)
    assert any(w['issue'] == 'volume_jump' for w in warns)

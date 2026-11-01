"""Treadmill days: no descent_session, D+ within the incline cap, runner notes."""

from services.plan_engine import generate_plan

TREADMILL = ['Monday', 'Tuesday', 'Thursday', 'Friday']


def _plan(**kw):
    return generate_plan(
        total_weeks=15, race_distance_km=34, race_elevation_m=2100, race_date='2027-02-07',
        athlete_weekly_km=75, athlete_weekly_elev=1200, athlete_longest_run_km=25,
        athlete_category='cat_1', long_run_day='Sunday', rest_days=[],
        mountain_days=['Wednesday', 'Saturday', 'Sunday'], strength_days=1,
        prefs={'terrain_profile': 'rolling_hills'}, **kw)


def test_treadmill_days_never_descend_and_respect_incline():
    weeks = _plan(treadmill_days=TREADMILL, treadmill_max_incline_pct=10)
    tm_days = [d for w in weeks for d in w['days'] if d['day'] in TREADMILL]
    assert all(d['workout_type'] != 'descent_session' for d in tm_days)
    for d in tm_days:
        if d['workout_type'] in ('rest', 'strength'):
            continue
        assert d['elevation_m'] <= d['distance_km'] * 100 + 1, d
        assert d.get('treadmill') and 'no decline' in d['notes']
    # Descent work still exists, on outdoor days.
    assert any(d['workout_type'] == 'descent_session' for w in weeks for d in w['days'])


def test_no_treadmill_unchanged():
    assert not any(d.get('treadmill') for w in _plan() for d in w['days'])


def test_treadmill_hill_repeats_are_sustained_blocks():
    weeks = _plan(treadmill_days=TREADMILL, treadmill_max_incline_pct=10)
    hr = [d for w in weeks for d in w['days']
          if d['day'] in TREADMILL and d['workout_type'] == 'hill_repeats']
    assert hr and all(d['elevation_m'] >= 200 for d in hr), hr
    assert all(d['elevation_m'] <= d['distance_km'] * 100 + 1 for d in hr)


def test_treadmill_easy_days_climb_for_mountain_race():
    weeks = _plan(treadmill_days=TREADMILL, treadmill_max_incline_pct=10)
    easy = [d for w in weeks for d in w['days']
            if d['day'] in TREADMILL and d['workout_type'] == 'easy' and d['distance_km'] >= 6]
    assert easy and all(d['elevation_m'] >= d['distance_km'] * 15 for d in easy), easy[:3]
    assert all(d['elevation_m'] <= d['distance_km'] * 100 + 1 for d in easy)


def test_weekly_dplus_stays_near_target():
    weeks = _plan(treadmill_days=TREADMILL, treadmill_max_incline_pct=10)
    for w in weeks:
        tot = sum(d['elevation_m'] for d in w['days'])
        tgt = w['_meta']['elev_planned_total_m']
        if tgt:
            assert tot <= tgt * 1.15 + 100, (w.get('week_number'), tot, tgt)

"""Coach-review #111-#115: reproducer from the GH issues (15 weeks, 34 km / 2100 m)."""

from services.plan_engine import generate_plan, validate_plan_feasibility

TREADMILL = ['Monday', 'Tuesday', 'Thursday', 'Friday']
BASE = dict(
    total_weeks=15, race_distance_km=34, race_elevation_m=2100, race_date='2027-02-07',
    athlete_weekly_km=65, athlete_weekly_elev=2000, athlete_longest_run_km=26,
    athlete_category='cat_1', long_run_day='Sunday', rest_days=[],
    mountain_days=['Wednesday', 'Saturday', 'Sunday'], treadmill_days=TREADMILL,
    treadmill_max_incline_pct=10, strength_days=1, strength_preferred_days=['Thursday'],
)


def _plan(prefs=None, **kw):
    p = {'terrain_profile': 'rolling_hills', **(prefs or {})}
    return generate_plan(**{**BASE, **kw}, prefs=p)


def _days(weeks, wt):
    return [(w['week_number'], d) for w in weeks for d in w['days'] if d['workout_type'] == wt]


def test_111_structured_sessions_not_clamped_by_midweek_cap():
    weeks = _plan()
    desc = _days(weeks, 'descent_session')
    assert desc and all(d['elevation_m'] >= 300 for _, d in desc)
    assert any(d['elevation_m'] >= 600 for _, d in desc)
    for wk, d in _days(weeks, 'hill_repeats'):
        if wk >= 5:  # Build: profile is 280 m, not the 200 m easy-day cap
            assert d['elevation_m'] >= 280
        assert 'targeting race km' not in d['title'] and 'x1.' not in d['title']
    # validator no longer flags them
    warns = validate_plan_feasibility(weeks, {'terrain_profile': 'rolling_hills'}, 'rolling_hills')
    assert not [w for w in warns if w['issue'] == 'midweek_elev_too_high']


def test_112_weekly_descent_from_late_base_not_in_last_week():
    weeks = _plan()
    with_desc = {wk for wk, _ in _days(weeks, 'descent_session')}
    assert {3, 4, 5, 6, 7, 9, 11} <= with_desc          # every non-recovery week, late Base on
    assert not with_desc & {12, 13, 14, 15}             # nothing in the last ~3 weeks


def test_113_strength_is_addon_when_athlete_runs_every_day():
    weeks = _plan()
    assert not _days(weeks, 'strength')
    for w in weeks[:11]:
        assert sum(d.get('strength', False) for d in w['days']) == 1
    # with a declared rest day the separate slot is kept
    w = _plan(rest_days=['Monday'])
    assert _days(w, 'strength')


def test_114_polarized_swaps_build_tempo_for_vo2_intervals():
    kw = dict(race_elevation_m=1000)   # below the descent threshold: Build keeps its quality slot
    tempo = _plan(**kw)
    assert _days(tempo, 'tempo')
    pol = _plan(prefs={'intensity_distribution': 'polarized'}, **kw)
    assert not _days(pol, 'tempo')
    vo2 = [d for wk, d in _days(pol, 'intervals') if d['title'].startswith('VO2 intervals')]
    assert vo2 and 'Z4-Z5' in vo2[0]['title']


def test_115_long_run_hours_model_long_long_and_no_build_dip():
    prefs = {'max_long_run_hours': 3, 'long_long_run_hours': 4, 'long_long_run_every_weeks': 4}
    weeks = _plan(prefs=prefs)
    lr = {w['week_number']: d['distance_km'] for w in weeks for d in w['days']
          if d['workout_type'] == 'long_run'}
    assert lr[9] > lr[7] and lr[9] > lr[11]               # long-long pulse only on its week
    warns = validate_plan_feasibility(weeks, {**prefs, 'terrain_profile': 'rolling_hills'},
                                      'rolling_hills')
    assert not [w for w in warns if w['issue'] == 'long_run_hours_above_cap']
    # no unexplained dip right before a recovery week; week 1 near current load
    plain = _plan()
    plr = {w['week_number']: d['distance_km'] for w in plain for d in w['days']
           if d['workout_type'] == 'long_run'}
    assert plr[7] >= plr[6] - 1
    assert plain[0]['total_km'] >= 0.9 * 65

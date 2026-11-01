"""Single-workout analysis: splits, zones, drift, climbs, intervals, ownership."""

from datetime import datetime

import numpy as np
import pytest

from app import create_app
from database import db
from models import Activity, User
from services import workout_analysis_service as wa
from services.agent.tool_handlers import handle_tool_call
from services.pace_zone_service import compute_hr_zones


def _flat(n=3000, v=3.0, hr=140):
    t = list(range(n))
    return {'time': t, 'distance': [v * i for i in t], 'velocity_smooth': [v] * n,
            'heartrate': [hr] * n, 'cadence': [85] * n, 'altitude': [100.0 + 0.001 * i for i in t],
            'grade_smooth': [0.0] * n, 'moving': [True] * n}


def _hill():
    """2 km flat, 1 km climb at 10 %, 1 km flat, 1 km descent at -10 %."""
    d = np.arange(0, 5000, 5.0)
    alt = np.interp(d, [0, 2000, 3000, 4000, 5000], [100, 100, 200, 200, 100])
    g = np.gradient(alt, d) * 100
    v = np.full(len(d), 3.0)
    t = np.cumsum(5.0 / v) - 5.0 / 3
    return {'time': t.tolist(), 'distance': d.tolist(), 'altitude': alt.tolist(),
            'grade_smooth': g.tolist(), 'velocity_smooth': v.tolist(), 'heartrate': [150] * len(d)}


def test_km_splits():
    rows = wa.splits(_flat(), 1000.0)
    assert len(rows) == 9
    assert rows[0]['pace_s_km'] == 333 and rows[0]['hr'] == 140 and rows[0]['cadence_spm'] == 170


def test_hr_zones_and_drift():
    zones = compute_hr_zones(hr_max=190, hr_rest=50)['zones']
    z = wa.hr_zone_times(_flat(hr=130), zones)
    assert abs(sum(v['pct'] for v in z.values()) - 100) < 0.5
    assert max(z.values(), key=lambda v: v['pct'])['pct'] > 99
    s = _flat()
    s['heartrate'] = [140] * 1500 + [154] * 1500
    assert wa.hr_drift(s)['decoupling_pct'] == pytest.approx(9.1, abs=0.5)
    assert wa.hr_drift(_flat())['decoupling_pct'] == 0


def test_climbs_and_descents():
    cd = wa.climbs_descents(_hill())
    assert [c['type'] for c in cd] == ['climb', 'descent']
    assert cd[0]['grade_pct'] == pytest.approx(10, abs=1) and cd[0]['elev_m'] == pytest.approx(100, abs=10)
    assert cd[0]['vam_m_h'] == pytest.approx(1080, rel=0.1)
    assert cd[1]['descent_speed_kmh'] == pytest.approx(10.8, abs=0.5)


def test_treadmill_has_no_altitude():
    s = _flat()
    s['altitude'] = [0.0] * len(s['time'])
    out = wa.summarize(s)
    assert not out['altitude_available'] and out['climbs_descents'] is None
    assert 'treadmill' in out['altitude_note'] and 'd_plus' not in out['splits'][0]
    assert wa.summarize(_hill())['altitude_available']


def test_interval_detection_speed_and_hr_fallback():
    n, v = 2100, []
    for i in range(n):  # 5 min warmup, 6 x (180 s hard, 120 s easy)
        v.append(2.5 if i < 300 or (i - 300) % 300 >= 180 else 4.5)
    s = {'time': list(range(n)), 'distance': np.cumsum(v).tolist(), 'velocity_smooth': v}
    r = wa.detect_intervals(s)
    assert r['signal'] == 'speed' and r['n_work'] == 6 and r['avg_work_s'] == pytest.approx(180, abs=10)
    # treadmill-style: constant belt speed, effort visible only in HR
    s2 = {'time': list(range(n)), 'distance': [3.0 * i for i in range(n)], 'velocity_smooth': [3.0] * n,
          'heartrate': [120 + (40 if i >= 300 and (i - 300) % 300 < 180 else 0) for i in range(n)]}
    assert wa.detect_intervals(s2)['signal'] == 'hr'
    assert wa.detect_intervals(_flat()) is None


def test_step_targets():
    zones = compute_hr_zones(hr_max=190, hr_rest=50)['zones']
    steps = [{'type': 'repeat', 'repeats': 2, 'steps': [
        {'type': 'work', 'duration_min': 10, 'target': {'type': 'hr', 'zone': 2}}]}]
    out = wa.step_targets(_flat(hr=140), steps, zones)
    assert len(out) == 2 and out[0]['target_met'] is True  # Z2 Karvonen 50+140*[.6,.7]
    out = wa.step_targets(_flat(hr=185), steps, zones)
    assert out[0]['target_met'] is False


@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_ownership_and_tools(app):
    u1 = User(strava_user_id=1, strava_username='a', access_token='a', refresh_token='r', expires_at=2**31)
    u2 = User(strava_user_id=2, strava_username='b', access_token='a', refresh_token='r', expires_at=2**31)
    db.session.add_all([u1, u2])
    db.session.commit()
    a = Activity(user_id=u1.id, strava_id=5, external_id='5', name='run', distance=9000,
                 start_date=datetime(2026, 5, 1, 7), sport_type='run', moving_time_s=3000, elevation_gain_m=0)
    a.streams = _flat()
    db.session.add(a)
    db.session.commit()

    d = handle_tool_call('get_activity_detail', {'activity_id': a.id}, u1.id)
    assert 'error' not in d and d['splits'] and d['hr_zones']
    assert 'error' in handle_tool_call('get_activity_detail', {'activity_id': a.id}, u2.id)
    assert 'error' in handle_tool_call('compare_to_plan', {'activity_id': a.id}, u2.id)
    assert handle_tool_call('compare_to_plan', {'activity_id': a.id}, u1.id)['matched'] is False
    lst = handle_tool_call('list_activities', {'start': '2026-04-30', 'end': '2026-05-02'}, u1.id)
    assert lst['count'] == 1 and lst['activities'][0]['avg_hr'] == 140
    assert handle_tool_call('list_activities', {'start': '2026-04-30', 'end': '2026-05-02'}, u2.id)['count'] == 0

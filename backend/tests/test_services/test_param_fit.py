"""Tier 2 fitter: grade units (F1), v_flat identifiability (F2), eligibility, stops, interval."""

import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app import create_app
from database import db
from models import Activity, User, UserActivityResidual
from services import parameter_learning_service as pls
from services.physics_model.core import normalized_cost_ratio
from services.physics_prediction_service import PhysicsPredictionService


def _streams(v_flat, k_up=1.0):
    """Flat at v_flat, uphill 5-15 % at v_flat / (Minetti(g) * 1.08 * k_up); grade_smooth in PERCENT."""
    grades_pct = [0.0] * 200 + [float(g) for g in range(5, 16) for _ in range(20)]
    vel = [v_flat if g == 0 else v_flat / (normalized_cost_ratio(g / 100) * 1.08 * k_up) for g in grades_pct]
    n = len(grades_pct)
    return {'distance': [i * 10.0 for i in range(n)], 'velocity_smooth': vel, 'grade_smooth': grades_pct,
            'altitude': [0.0] * n, 'moving': [True] * n}


def _act(v_flat, k_up=1.0):
    return SimpleNamespace(streams=_streams(v_flat, k_up))


def test_fit_recovers_v_flat_and_k_up_with_percent_grades():
    p = pls.fit_params([_act(3.0)] * 3)
    assert p['v_flat'] == pytest.approx(3.0, rel=0.02)
    assert 0.9 <= p['k_up'] <= 1.1
    assert p['fatigue_alpha'] == 0.3


def test_fit_params_are_plain_floats(monkeypatch):
    # The real downhill fit returns np.float64, which psycopg2 cannot bind.
    import numpy as np
    monkeypatch.setattr(pls, 'calibrate_user_params', lambda dfs: {'v_flat': np.float64(2.7), 'k_tech': np.float64(1.18)})
    assert all(type(v) is float for v in pls.fit_params([_act(3.0)]).values())


def test_v_flat_follows_flat_speed():
    fast, slow = pls.fit_params([_act(3.0)]), pls.fit_params([_act(2.5)])
    assert slow['v_flat'] / fast['v_flat'] == pytest.approx(2.5 / 3.0, rel=0.02)


def test_stop_share_median_then_clip():
    acts = [SimpleNamespace(moving_time_s=1000, elapsed_time_s=e) for e in (1010, 1030, 1050)]
    assert pls.stop_share(acts) == pytest.approx(0.03)
    assert pls.stop_share([SimpleNamespace(moving_time_s=1000, elapsed_time_s=2000)]) == 0.15
    assert pls.stop_share([SimpleNamespace(moving_time_s=1000, elapsed_time_s=None)]) == 0.0


def test_prediction_interval_quantiles_and_fallbacks():
    errs = list(np.linspace(-0.2, 0.2, 11))  # sorted; n=11 -> conformal ranks 1 and 11
    lo, hi = pls.prediction_interval(errs[::-1], 'TIER_2_PARAMETER_LEARNING')
    assert lo == pytest.approx(math.exp(-0.2))
    assert hi == pytest.approx(math.exp(0.2))
    twenty = list(np.linspace(-0.19, 0.19, 20))  # n=20 -> ranks 2 and 19
    assert pls.prediction_interval(twenty, 'TIER_2_PARAMETER_LEARNING') == (
        pytest.approx(math.exp(twenty[1])), pytest.approx(math.exp(twenty[18])))
    assert pls.prediction_interval(errs[:5], 'TIER_2_PARAMETER_LEARNING') == (0.80, 1.20)
    assert pls.prediction_interval(errs, 'TIER_1_PHYSICS') == (0.75, 1.25)
    assert pls.accuracy(errs[:5]) is None
    assert pls.accuracy(errs) == {'p80_pct': round(100 * np.quantile(np.abs(np.exp(errs) - 1), 0.8)), 'n': 11}


def test_physics_predict_honours_fatigue_alpha():
    pts = [{'distance': d, 'elevation': 1500 - d * 0.1} for d in range(0, 15001, 50)]
    base = {'v_flat': 3.0, 'k_up': 1.0, 'k_tech': 1.0, 'a_param': 3.0,
            'k_terrain_up': 1.08, 'k_terrain_down': 1.12, 'k_terrain_flat': 1.05}
    t0 = PhysicsPredictionService().predict(pts, {**base, 'fatigue_alpha': 0.0})['total_time_seconds']
    t2 = PhysicsPredictionService().predict(pts, {**base, 'fatigue_alpha': 2.0})['total_time_seconds']
    assert t2 > t0


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


def test_eligible_activities_drops_excluded_and_slow(app):
    user = User(strava_user_id=1, strava_username='x', access_token='a', refresh_token='r', expires_at=2**31)
    db.session.add(user)
    db.session.commit()
    t0 = datetime(2026, 1, 1)
    # 10 km, 0 D+: normal runs at 3000 s, one at 6000 s (2x median pace), one excluded.
    for i, mov in enumerate([3000, 3100, 2900, 3000, 6000, 3000]):
        a = Activity(user_id=user.id, strava_id=100 + i, external_id=str(100 + i), name=f'r{i}',
                     distance=10000, start_date=t0 + timedelta(days=i), sport_type='trail_run',
                     moving_time_s=mov, elapsed_time_s=mov, elevation_gain_m=0)
        a.streams = _streams(3.0)
        db.session.add(a)
    db.session.add(UserActivityResidual(user_id=user.id, activity_id='105', activity_date=t0,
                                        segments=[], excluded_from_training=True))
    db.session.commit()

    ids = [a.strava_id for a in pls.eligible_activities(user.id)]
    assert ids == [100, 101, 102, 103]
    assert [a.strava_id for a in pls.eligible_activities(user.id, before=t0 + timedelta(days=2))] == [100, 101]


def _hybrid_with_record(stop_share=0.02, log_errors=None):
    from unittest.mock import MagicMock
    from services.hybrid_prediction_service import HybridPredictionService
    record = SimpleNamespace(
        to_dict=lambda: {'v_flat': 2.8, 'k_up': 1.0, 'k_tech': 1.0, 'a_param': 3.0, 'k_terrain_up': 1.08,
                         'k_terrain_down': 1.12, 'k_terrain_flat': 1.05, 'fatigue_alpha': 0.3},
        param_uncertainties={'stop_share': stop_share, 'log_errors': log_errors or []},
        n_activities_used=10, optimization_score=0.08)
    repo = MagicMock()
    repo.get_for_user.return_value = record
    model_repo = MagicMock()
    model_repo.get_for_user.return_value = None
    return HybridPredictionService(learned_params_repo=repo, residual_model_repo=model_repo)


ROUTE = [{'distance': d, 'elevation': 500 + (d % 4000) * 0.05} for d in range(0, 20001, 50)]


def test_hybrid_effort_scales_moving_time_for_tier2(app):
    svc = _hybrid_with_record(stop_share=0.0)
    train = svc.predict(3, ROUTE, effort='training')
    race = svc.predict(3, ROUTE, effort='race')
    assert train['metadata']['tier'] == 'TIER_2_PARAMETER_LEARNING'
    assert race['moving_time_seconds'] == pytest.approx(0.95 * train['moving_time_seconds'])
    assert sum(s['time_s'] for s in race['segments']) == pytest.approx(race['moving_time_seconds'])


def test_hybrid_finish_adds_passive_and_aid_stops(app):
    errs = list(np.linspace(-0.2, 0.2, 11))
    r = _hybrid_with_record(stop_share=0.03, log_errors=errs).predict(
        3, ROUTE, aid_stops={'count': 4, 'minutes_each': 2.5})
    assert r['stop_time_seconds'] == pytest.approx(0.03 * r['moving_time_seconds'] + 600)
    assert r['total_time_seconds'] == pytest.approx(r['moving_time_seconds'] + r['stop_time_seconds'])
    lo, hi = pls.prediction_interval(errs, 'TIER_2_PARAMETER_LEARNING')
    assert r['confidence_interval']['upper_seconds'] == pytest.approx(r['total_time_seconds'] * hi)
    assert r['metadata']['accuracy']['n'] == 11


def test_predict_request_validates_aid_stops():
    from api.validation import validate_predict_request
    assert validate_predict_request({'gpx_id': 1, 'aid_stops': {'count': 5, 'minutes_each': 3}})[0]
    assert not validate_predict_request({'gpx_id': 1, 'aid_stops': {'count': 61, 'minutes_each': 3}})[0]
    assert not validate_predict_request({'gpx_id': 1, 'aid_stops': {'count': 2, 'minutes_each': -1}})[0]


def test_predict_request_validates_target_hr():
    from api.validation import validate_predict_request
    assert validate_predict_request({'gpx_id': 1, 'target_hr': 160})[0]
    assert not validate_predict_request({'gpx_id': 1, 'target_hr': 400})[0]
    assert not validate_predict_request({'gpx_id': 1, 'target_hr': True})[0]

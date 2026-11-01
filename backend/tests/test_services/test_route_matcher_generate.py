"""match_routes_to_plan generates ORS routes for library misses (mocked ORS)."""

from types import SimpleNamespace

import pytest

from app import create_app
from database import db
from models import User
from models.training_route import TrainingRoute
from services import route_matcher
from services.route_generation_service import RouteGenerationService


@pytest.fixture
def user():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        u = User(strava_user_id=1, strava_username='f', training_base_lat=45.0, training_base_lon=9.0)
        db.session.add(u)
        db.session.commit()
        yield u
        db.session.remove()
        db.drop_all()


def _plan(uid, kms):
    days = [{'day': i, 'workout_type': 'easy', 'distance_km': k, 'elevation_m': 0} for i, k in enumerate(kms)]
    return SimpleNamespace(user_id=uid, weeks=[{'week_number': 1, 'days': days}])


def _patch(monkeypatch, fn):
    monkeypatch.setattr(RouteGenerationService, '__init__', lambda self: setattr(self, 'api_key', 'k'))
    monkeypatch.setattr(RouteGenerationService, 'generate_loop_route',
                        lambda self, **kw: fn(kw['target_distance_km']))
    monkeypatch.setattr('services.route_suggestion_service.sync_frequent_routes', lambda uid: 0)


def _ok(km):
    return {'route_data': [{'lat': 45, 'lon': 9}], 'distance_km': km,
            'elevation_gain_m': 10, 'elevation_loss_m': 10}


def test_generates_reuses_and_caps(user, monkeypatch):
    calls = []
    _patch(monkeypatch, lambda km: calls.append(km) or _ok(km))
    plan = _plan(user.id, [10, 10.5, 20, 40, 80, 160])
    plan.weeks[0]['days'].append({'day': 9, 'workout_type': 'easy', 'distance_km': 10, 'treadmill': True})
    route_matcher.match_routes_to_plan(plan, {})
    days = plan.weeks[0]['days']
    assert len(calls) == 3  # cap; 10.5 reused the 10km route
    assert [d['route_match_quality'] for d in days] == ['generated'] * 4 + ['unmatched'] * 3
    assert days[0]['route_id'] == days[1]['route_id']
    assert TrainingRoute.query.filter_by(source='generated').count() == 3


def test_ors_failure_leaves_unmatched(user, monkeypatch):
    def boom(km):
        raise RuntimeError('ors down')
    _patch(monkeypatch, boom)
    plan = _plan(user.id, [10])
    route_matcher.match_routes_to_plan(plan, {})
    assert plan.weeks[0]['days'][0]['route_match_quality'] == 'unmatched'

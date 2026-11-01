"""Training locations: weekday exclusivity and per-day route matching (GH #120)."""

import pytest

from app import create_app
from database import db
from models import User
from models.training_route import TrainingRoute
from repositories import TrainingLocationRepository
from models.training_location import TrainingLocation
from services.route_matcher import match_routes_to_plan, set_day_location


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


@pytest.fixture
def setup(app):
    u = User(strava_user_id=9, strava_username='loc-user')
    db.session.add(u)
    db.session.commit()
    repo = TrainingLocationRepository()
    home = TrainingLocation(user_id=u.id, name='Casa', lat=42.66, lon=13.70, radius_km=10, weekdays=[])
    work = TrainingLocation(user_id=u.id, name='Lavoro', lat=42.46, lon=14.21, radius_km=10, weekdays=[])
    repo.create(home)
    repo.create(work)
    repo.assign_weekdays(u.id, home, [0, 1])
    repo.assign_weekdays(u.id, work, [1])  # steals Tuesday from home
    for name, lat, lon in (('near home', 42.66, 13.71), ('near work', 42.46, 14.21)):
        db.session.add(TrainingRoute(user_id=u.id, name=name, route_data=[], distance_km=10,
                                     elevation_gain_m=100, center_lat=lat, center_lon=lon))
    db.session.commit()
    return u, home, work


class _Plan:
    def __init__(self, user_id, days):
        self.user_id = user_id
        self.weeks = [{'week_number': 1, 'days': days}]


def _day(name, **kw):
    return {'day': name, 'workout_type': 'easy', 'distance_km': 10, 'elevation_m': 100, **kw}


def _names(user_id, plan):
    names = {r.id: r.name for r in TrainingRoute.query.filter_by(user_id=user_id)}
    return [names.get(d['route_id']) for d in plan.weeks[0]['days']]


def test_weekday_exclusivity(app, setup):
    _, home, work = setup
    assert home.weekdays == [0]
    assert work.weekdays == [1]


def test_matcher_uses_weekday_location_override_and_skips_treadmill(app, setup):
    u, home, work = setup
    plan = _Plan(u.id, [_day('Monday'), _day('Tuesday'), _day('Tuesday', location_id=home.id),
                        _day('Monday', treadmill=True)])
    match_routes_to_plan(plan, {})
    assert _names(u.id, plan)[:3] == ['near home', 'near work', 'near home']
    assert plan.weeks[0]['days'][3]['resolved_location_id'] is None


def test_set_day_location_rematches(app, setup):
    u, home, work = setup
    plan = _Plan(u.id, [_day('Monday')])
    match_routes_to_plan(plan, {})
    day = set_day_location(plan, 1, 'Monday', work.id)
    assert day['location_id'] == work.id and day['resolved_location_id'] == work.id
    assert _names(u.id, plan) == ['near work']
    with pytest.raises(ValueError):
        set_day_location(plan, 1, 'Monday', 9999)


def test_weekday_change_rematches_only_future_unoverridden_days(app, setup):
    from datetime import date, timedelta
    from models.training_plan import TrainingPlan
    from services.route_matcher import rematch_future_plan_days
    u, home, work = setup
    mon = date.today() + timedelta(days=7 - date.today().weekday())  # next Monday
    past = mon - timedelta(days=14)
    days = [_day('Monday', date=mon.isoformat()),
            _day('Monday', date=mon.isoformat(), location_id=home.id),
            _day('Monday', date=past.isoformat())]
    plan = TrainingPlan(user_id=u.id, plan_name='p', status='active', weeks=[{'week_number': 1, 'days': days}])
    db.session.add(plan)
    db.session.commit()
    match_routes_to_plan(plan, {})
    TrainingLocationRepository().assign_weekdays(u.id, work, [0])  # work takes Monday
    assert rematch_future_plan_days(u.id) == 1
    out = plan.weeks[0]['days']
    assert [d['resolved_location_id'] for d in out] == [work.id, home.id, home.id]
    assert rematch_future_plan_days(u.id) == 0  # nothing left to change


def test_swap_carries_route_and_rematches_on_other_location(app, setup):
    from services.plan_adjustment_service import PlanAdjustmentService
    u, home, work = setup  # Monday=home, Tuesday=work
    a, b = _day('Monday', workout_type='tempo'), _day('Tuesday')
    match_routes_to_plan(_Plan(u.id, [a, b]), {})
    assert (a['route_id'], b['route_id']) != (None, None) and a['route_id'] != b['route_id']
    old_a = a['route_id']
    PlanAdjustmentService._swap_day_payloads(a, b)
    from services.route_matcher import rematch_stale_days
    rematch_stale_days(u.id, [a, b])
    assert a['workout_type'] == 'easy' and b['workout_type'] == 'tempo'
    assert b['resolved_location_id'] == work.id and b['route_id'] != old_a  # re-matched to Tuesday's place
    # explicit override moves with the workout and is not re-matched
    c = _day('Monday', location_id=work.id)
    match_routes_to_plan(_Plan(u.id, [c]), {})
    assert rematch_stale_days(u.id, [c]) == 0

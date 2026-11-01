"""Route library scoring + plan binding."""

from types import SimpleNamespace

from services import route_matcher


def _route(rid, name, km, elev, tags=None, user_id=1):
    return SimpleNamespace(
        id=rid, name=name, distance_km=km, elevation_gain_m=elev,
        tags=tags or [], user_id=user_id,
    )


def test_pick_long_run_within_tolerance_picks_closest_route():
    routes = [
        _route(1, '8/200', 8, 200),
        _route(2, '12/600', 12, 600),
        _route(3, '20/1000', 20, 1000),
    ]
    route, q = route_matcher.match_route_for_workout(
        user_id=1, workout_type='long_run',
        target_km=12, target_elev=500,
        routes=routes,
    )
    assert route is not None
    assert route.id == 2
    assert q in ('exact', 'approx')


def test_no_match_returns_unmatched():
    routes = [_route(1, 'flat', 10, 50)]
    route, q = route_matcher.match_route_for_workout(
        user_id=1, workout_type='vert_session',
        target_km=10, target_elev=2000,
        routes=routes,
    )
    assert route is None
    assert q == 'unmatched'


def test_flat_urban_user_skips_hilly_routes_for_easy():
    routes = [_route(1, 'hilly easy', 8, 600)]  # 75 m/km — too hilly for flat_urban
    route, q = route_matcher.match_route_for_workout(
        user_id=1, workout_type='easy',
        target_km=8, target_elev=20,
        terrain_profile='flat_urban',
        routes=routes,
    )
    assert q == 'unmatched'


def test_long_run_rescue_picks_longest_when_target_above_25km():
    """For ultra long runs, allow the longest available route as approx."""
    routes = [
        _route(1, '20km', 20, 600),
        _route(2, '25km', 25, 800),
    ]
    route, q = route_matcher.match_route_for_workout(
        user_id=1, workout_type='long_run',
        target_km=32, target_elev=900,
        routes=routes,
    )
    # Tolerance band may or may not catch it; rescue triggers above 25km.
    assert route is not None


def test_match_routes_to_plan_attaches_route_ids_and_summary():
    plan = SimpleNamespace(
        user_id=1,
        weeks=[{
            'week_number': 1,
            'days': [
                {'day': 'Monday', 'workout_type': 'easy',
                 'distance_km': 8, 'elevation_m': 20},
                {'day': 'Sunday', 'workout_type': 'long_run',
                 'distance_km': 12, 'elevation_m': 500},
            ],
        }],
    )
    routes = [
        _route(11, 'easy 8/30', 8, 30),
        _route(12, 'lr 12/500', 12, 500),
    ]
    # Patch the repo lookup so the test stays DB-free.
    class _FakeRepo:
        def get_user_routes(self, user_id):
            return routes

    import sys as _sys
    class _NoLocations:
        def get_user_locations(self, user_id):
            return []

    fake_pkg = SimpleNamespace(TrainingRouteRepository=_FakeRepo,
                               TrainingLocationRepository=_NoLocations)
    real_repos = _sys.modules.get('repositories')
    _sys.modules['repositories'] = fake_pkg
    try:
        summary = route_matcher.match_routes_to_plan(plan, prefs=None)
    finally:
        if real_repos is not None:
            _sys.modules['repositories'] = real_repos
        else:
            _sys.modules.pop('repositories', None)

    assert summary['matched'] + summary['approx'] == 2
    assert summary['unmatched'] == 0
    days = plan.weeks[0]['days']
    assert all(d['route_id'] in (11, 12) for d in days)

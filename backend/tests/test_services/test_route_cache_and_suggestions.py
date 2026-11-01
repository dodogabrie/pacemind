"""Unit tests for ORS cache key determinism and route suggestion clustering."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.route_generation_service import RouteGenerationService
from services import route_suggestion_service


# ---------------------------------------------------------------------------
# ORS cache key
# ---------------------------------------------------------------------------

def test_cache_key_is_deterministic():
    """Identical waypoints should always hash to the same key."""
    coords = [[7.6900, 45.0700], [7.7000, 45.0750], [7.6900, 45.0700]]
    k1 = RouteGenerationService._cache_key(coords)
    k2 = RouteGenerationService._cache_key(list(coords))  # different list, same content
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_cache_key_ignores_subdecimal_jitter():
    """Tiny float wobble below 5 decimals must not invalidate the cache."""
    a = [[7.69001, 45.07001], [7.70001, 45.07501]]
    b = [[7.690012345, 45.070009999], [7.700014321, 45.075011111]]
    assert RouteGenerationService._cache_key(a) == RouteGenerationService._cache_key(b)


def test_cache_key_distinguishes_meaningfully_different_routes():
    """Coordinates that differ at 5 decimals must produce different keys."""
    a = [[7.69000, 45.07000], [7.70000, 45.07500]]
    b = [[7.69001, 45.07000], [7.70000, 45.07500]]
    assert RouteGenerationService._cache_key(a) != RouteGenerationService._cache_key(b)


def test_cache_key_order_matters():
    """Reversing the route should give a different key (out vs back)."""
    a = [[7.69, 45.07], [7.70, 45.08]]
    b = [[7.70, 45.08], [7.69, 45.07]]
    assert RouteGenerationService._cache_key(a) != RouteGenerationService._cache_key(b)


def test_normalize_handles_dict_and_list_inputs():
    """Both [lat, lon] lists and {lat, lon} dicts should normalize to [lon, lat]."""
    out = RouteGenerationService._normalize_to_lonlat(
        [[45.07, 7.69], {'lat': 45.08, 'lon': 7.70}]
    )
    assert out == [[7.69, 45.07], [7.70, 45.08]]


# ---------------------------------------------------------------------------
# Route suggestion clustering
# ---------------------------------------------------------------------------

def _fake_activity(strava_id, name, start_lat, start_lon, distance_m, days_ago, n_points=20, with_streams=True):
    latlng = [[start_lat + i * 0.0001, start_lon + i * 0.0001] for i in range(n_points)]
    altitude = [100 + i for i in range(n_points)]
    streams = {'latlng': latlng, 'altitude': altitude} if with_streams else None
    return SimpleNamespace(
        id=strava_id,
        strava_id=strava_id,
        name=name,
        distance=distance_m,
        start_date=datetime.now(timezone.utc) - timedelta(days=days_ago),
        streams=streams,
    )


class _FakeRepo:
    def __init__(self, activities):
        self._activities = activities

    def find_by(self, **kwargs):
        return list(self._activities)


def test_clustering_groups_repeated_routes(monkeypatch):
    """Three runs from the same start with similar distance form one cluster."""
    activities = [
        _fake_activity(1, 'Morning run',     45.07, 7.69, 8000,  5),
        _fake_activity(2, 'Morning run',     45.07, 7.69, 8200,  3),
        _fake_activity(3, 'Morning run',     45.07, 7.69, 7900,  1),
        # Different start point, different cluster:
        _fake_activity(4, 'Trail',           46.00, 8.00, 25000, 7),
    ]
    fake_repo = _FakeRepo(activities)
    monkeypatch.setattr(
        route_suggestion_service,
        'ActivityRepository',
        lambda: fake_repo,
        raising=False,
    )

    # Patch the import inside find_frequent_routes
    import repositories
    monkeypatch.setattr(repositories, 'ActivityRepository', lambda: fake_repo)

    suggestions = route_suggestion_service.find_frequent_routes(user_id=1)

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s['frequency'] == 3
    assert s['representative_strava_id'] == 3  # most recent
    assert abs(s['avg_distance_km'] - 8.03) < 0.05
    assert len(s['thumbnail']) > 0


def test_clustering_drops_singletons(monkeypatch):
    """Activities that only appear once should NOT surface as suggestions."""
    activities = [
        _fake_activity(1, 'Once-only', 45.07, 7.69, 10000, 5),
    ]
    fake_repo = _FakeRepo(activities)
    import repositories
    monkeypatch.setattr(repositories, 'ActivityRepository', lambda: fake_repo)

    suggestions = route_suggestion_service.find_frequent_routes(user_id=1)
    assert suggestions == []


def test_clustering_separates_short_and_long_runs_from_same_start(monkeypatch):
    """Same trailhead but very different distances should be different clusters."""
    activities = [
        _fake_activity(1, 'Short loop', 45.07, 7.69, 5000,  5),
        _fake_activity(2, 'Short loop', 45.07, 7.69, 5200,  3),
        _fake_activity(3, 'Long loop',  45.07, 7.69, 25000, 4),
        _fake_activity(4, 'Long loop',  45.07, 7.69, 26000, 2),
    ]
    fake_repo = _FakeRepo(activities)
    import repositories
    monkeypatch.setattr(repositories, 'ActivityRepository', lambda: fake_repo)

    suggestions = route_suggestion_service.find_frequent_routes(user_id=1)
    assert len(suggestions) == 2
    distances = sorted(s['avg_distance_km'] for s in suggestions)
    assert distances[0] < 6
    assert distances[1] > 20


def test_clustering_skips_activities_without_streams(monkeypatch):
    """Activities with no GPS streams must be ignored."""
    activities = [
        _fake_activity(1, 'A', 45.07, 7.69, 8000, 5, with_streams=False),
        _fake_activity(2, 'A', 45.07, 7.69, 8000, 4, with_streams=False),
    ]
    fake_repo = _FakeRepo(activities)
    import repositories
    monkeypatch.setattr(repositories, 'ActivityRepository', lambda: fake_repo)

    suggestions = route_suggestion_service.find_frequent_routes(user_id=1)
    assert suggestions == []

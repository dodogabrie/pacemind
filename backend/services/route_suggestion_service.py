"""Route suggestion service — clusters Strava activities into recurring routes.

The user's imported activities encode the routes they actually run. Most runners
have a small set of habitual loops (out-the-door, the regular long run, the
weekend trail). Surfacing these as one-click "Save as route" suggestions removes
the need to draw or auto-generate them, and costs zero ORS calls.

Approach (v1, deliberately simple — no sklearn, no shapely):
  1. Bucket activities by start point + distance bucket. Two activities that
     start within ~110m and have similar total length are treated as the same
     habitual route.
  2. Drop singleton clusters — we only suggest a route if it's been run twice
     or more.
  3. Pick the most recent activity in each cluster as the representative
     polyline (freshest GPS, freshest fitness).
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


# Coordinate rounding for start-point bucketing. 3 decimals ≈ 110m.
_START_BUCKET_DECIMALS = 3

# Two activities count as the same route if they start at the same bucket AND
# their distances are within this relative tolerance. Greedy grouping over
# distance-sorted activities — robust to boundary effects that hard buckets
# (e.g. round(d/2)) suffer from when a value lands near a boundary.
_DISTANCE_REL_TOLERANCE = 0.20

# How many points in the thumbnail polyline returned to the frontend.
_THUMBNAIL_POINTS = 60

# Minimum cluster size to surface as a suggestion.
_MIN_FREQUENCY = 2

# How far back to look. Habits older than this are likely stale.
_LOOKBACK_DAYS = 365


def find_frequent_routes(user_id: int, limit: int = 10) -> List[Dict]:
    """Cluster a user's activities into recurring routes.

    Returns a list of suggestions, sorted by frequency descending. Each entry:
      {
        'cluster_id': str,
        'representative_activity_id': int,         # local DB id
        'representative_strava_id': int,
        'name': str,                               # name of the most recent activity
        'frequency': int,                          # how many times run
        'last_run_at': iso timestamp,
        'first_run_at': iso timestamp,
        'avg_distance_km': float,
        'avg_elevation_gain_m': float,
        'thumbnail': [{lat, lon}, ...],            # downsampled polyline
        'start_lat': float,
        'start_lon': float,
      }
    """
    from repositories import ActivityRepository

    repo = ActivityRepository()
    activities = repo.find_by(user_id=user_id)
    if not activities:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    by_start: Dict[str, List] = defaultdict(list)

    for act in activities:
        streams = act.streams
        if not streams:
            continue
        latlng = streams.get('latlng') or []
        if len(latlng) < 10:
            continue

        start_date = act.start_date
        if start_date is not None:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            if start_date < cutoff:
                continue

        start = latlng[0]
        bucket_lat = round(start[0], _START_BUCKET_DECIMALS)
        bucket_lon = round(start[1], _START_BUCKET_DECIMALS)
        start_key = f"{bucket_lat:.3f},{bucket_lon:.3f}"
        by_start[start_key].append(act)

    clusters: Dict[str, List] = {}
    for start_key, acts in by_start.items():
        # Greedy grouping by distance: sort, then walk the list keeping a
        # running anchor; whenever the next activity's distance differs from
        # the anchor by more than _DISTANCE_REL_TOLERANCE, start a new group.
        sorted_acts = sorted(acts, key=lambda a: (a.distance or 0))
        group_idx = 0
        anchor_km = None
        for act in sorted_acts:
            distance_km = (act.distance or 0) / 1000
            if anchor_km is None or anchor_km == 0:
                anchor_km = distance_km
            elif abs(distance_km - anchor_km) / anchor_km > _DISTANCE_REL_TOLERANCE:
                group_idx += 1
                anchor_km = distance_km
            cluster_id = f"{start_key}|g{group_idx}"
            clusters.setdefault(cluster_id, []).append(act)

    suggestions = []
    for cluster_id, acts in clusters.items():
        if len(acts) < _MIN_FREQUENCY:
            continue

        acts_sorted = sorted(
            acts,
            key=lambda a: a.start_date or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        representative = acts_sorted[0]
        latlng = representative.streams.get('latlng') or []
        altitude = representative.streams.get('altitude') or []

        thumbnail = _downsample(latlng, _THUMBNAIL_POINTS)
        elev_gain = _compute_elevation_gain(altitude)

        distances = [(a.distance or 0) / 1000 for a in acts]
        avg_distance = sum(distances) / len(distances)

        suggestions.append({
            'cluster_id': cluster_id,
            'representative_activity_id': representative.id,
            'representative_strava_id': representative.strava_id,
            'name': representative.name,
            'frequency': len(acts),
            'last_run_at': _iso(acts_sorted[0].start_date),
            'first_run_at': _iso(acts_sorted[-1].start_date),
            'avg_distance_km': round(avg_distance, 2),
            'avg_elevation_gain_m': round(elev_gain),
            'thumbnail': thumbnail,
            'start_lat': round(latlng[0][0], 6),
            'start_lon': round(latlng[0][1], 6),
        })

    suggestions.sort(key=lambda s: (s['frequency'], s['last_run_at'] or ''), reverse=True)
    return suggestions[:limit]


def _downsample(latlng: List, max_points: int) -> List[Dict]:
    if not latlng:
        return []
    step = max(1, len(latlng) // max_points)
    return [{'lat': p[0], 'lon': p[1]} for p in latlng[::step]]


def _compute_elevation_gain(altitude: List) -> float:
    if not altitude or len(altitude) < 2:
        return 0.0
    gain = 0.0
    for i in range(1, len(altitude)):
        delta = altitude[i] - altitude[i - 1]
        if delta > 0:
            gain += delta
    return gain


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


_MAX_FREQUENT_ROUTES = 10


def build_route_from_activity(activity, user_id: int, name: Optional[str] = None,
                              source: str = 'strava', generation_params: Optional[dict] = None):
    """Build an unsaved TrainingRoute from an activity's streams."""
    import numpy as np
    from api.routes import _auto_tag
    from models.training_route import TrainingRoute

    latlng = activity.streams.get('latlng', [])
    altitude = activity.streams.get('altitude', [])
    distance = activity.streams.get('distance', [])

    route_data = [
        {'lat': ll[0], 'lon': ll[1], 'elevation': alt,
         'distance': distance[i] if i < len(distance) else 0}
        for i, (ll, alt) in enumerate(zip(latlng, altitude))
    ]
    elev_diffs = np.diff(np.array(altitude))
    elevation_gain = float(np.sum(elev_diffs[elev_diffs > 0]))
    elevation_loss = float(np.abs(np.sum(elev_diffs[elev_diffs < 0])))
    distance_km = distance[-1] / 1000 if distance else 0

    return TrainingRoute(
        user_id=user_id,
        name=name or activity.name,
        source=source,
        route_data=route_data,
        distance_km=round(distance_km, 2),
        elevation_gain_m=round(elevation_gain),
        elevation_loss_m=round(elevation_loss),
        center_lat=round(sum(p[0] for p in latlng) / len(latlng), 6),
        center_lon=round(sum(p[1] for p in latlng) / len(latlng), 6),
        tags=_auto_tag(distance_km, elevation_gain),
        generation_params=generation_params,
    )


# TODO(routes #42 — see GH issues): no refresh on cluster change, no terrain enrichment, imports api._auto_tag.
def sync_frequent_routes(user_id: int) -> int:
    """Save recurring-route clusters as TrainingRoute(source='frequent').

    Idempotent: a cluster is skipped if a frequent route already carries its
    representative activity id. Never touches other routes. Returns # created.
    """
    from repositories import ActivityRepository, TrainingRouteRepository

    repo = TrainingRouteRepository()
    existing = repo.get_user_routes(user_id)
    seen = {(r.generation_params or {}).get('representative_activity_id')
            for r in existing if r.source == 'frequent'}
    room = _MAX_FREQUENT_ROUTES - len(seen)
    created = 0
    for s in find_frequent_routes(user_id, limit=_MAX_FREQUENT_ROUTES):
        if created >= room:
            break
        if s['representative_activity_id'] in seen:
            continue
        act = ActivityRepository().find_one_by(id=s['representative_activity_id'], user_id=user_id)
        route = build_route_from_activity(
            act, user_id, source='frequent',
            generation_params={'representative_activity_id': act.id, 'frequency': s['frequency']})
        repo.create(route)
        created += 1
    if created:
        repo.commit()
    return created

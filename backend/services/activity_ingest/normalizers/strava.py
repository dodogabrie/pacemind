"""Strava -> NormalizedActivity.

Wraps the payload `strava_sync_service` already has in hand: an activity dict
straight from the Strava list API plus the streams dict from
`StravaService.download_streams`. Strava already returns the canonical stream
keys, so there is nothing to derive here — `derive_streams()` exists for the
sources that do not.
"""

from datetime import datetime, timezone

from services.activity_ingest import NormalizedActivity


# Strava's `sport_type` vocabulary -> ours.
SPORT_TYPES = {
    'Run': 'run',
    'TrailRun': 'trail_run',
    'VirtualRun': 'run',
    'Hike': 'hike',
    'Walk': 'hike',
}


def _parse_start(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def normalize_strava(activity_data: dict, streams: dict = None) -> NormalizedActivity:
    """Build a NormalizedActivity from a Strava activity dict + its streams."""
    raw_type = activity_data.get('sport_type') or activity_data.get('type')
    # Strava hands us the wall clock for free; no need to guess it from coords.
    local = _parse_start(activity_data.get('start_date_local'))
    latlng = activity_data.get('start_latlng') or [None, None]
    return NormalizedActivity(
        source='strava',
        external_id=activity_data['id'],
        name=activity_data.get('name', 'Unnamed Activity'),
        start_date=_parse_start(activity_data['start_date']),
        distance_m=activity_data.get('distance', 0),
        streams=streams or {},
        moving_time_s=activity_data.get('moving_time'),
        elapsed_time_s=activity_data.get('elapsed_time'),
        elevation_gain_m=activity_data.get('total_elevation_gain'),
        sport_type=SPORT_TYPES.get(raw_type, 'other' if raw_type else None),
        start_date_local=local.replace(tzinfo=None) if local else None,
        # workout_type 1 = "Race" for runs. Absent key -> None: leave the flag alone.
        is_race=(activity_data['workout_type'] == 1) if 'workout_type' in activity_data else None,
        start_lat=latlng[0] if len(latlng) == 2 else None,
        start_lng=latlng[1] if len(latlng) == 2 else None,
    )

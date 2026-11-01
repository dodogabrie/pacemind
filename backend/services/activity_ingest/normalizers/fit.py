"""FIT file -> NormalizedActivity.

The preferred format: the watch's own record, with sensor-derived distance and
speed plus HR, cadence and power. Where a FIT gives us a number directly we
take it rather than reconstructing it from coordinates — `derive_streams()`
accepts the file's cumulative distance for exactly this reason.
"""

from datetime import timezone
from io import BytesIO

from services.activity_ingest import NormalizedActivity
from services.activity_ingest.streams import derive_streams
from services.activity_ingest.normalizers import (
    UnusableActivity, activity_name, content_id, map_sport, summarize)

# FIT stores coordinates as semicircles: 2^31 semicircles == 180 degrees.
SEMICIRCLES_TO_DEGREES = 180.0 / (2 ** 31)


def _first(values, *names):
    for name in names:
        value = values.get(name)
        if value is not None:
            return value
    return None


def normalize_fit(data: bytes, filename: str = '') -> NormalizedActivity:
    """Parse a FIT activity file into a NormalizedActivity."""
    try:
        from fitparse import FitFile
    except ImportError as e:  # pragma: no cover - dependency is in requirements
        raise UnusableActivity('fitparse is not installed') from e

    try:
        fit = FitFile(BytesIO(data))
        records = [m.get_values() for m in fit.get_messages('record')]
        sessions = [m.get_values() for m in fit.get_messages('session')]
    except Exception as e:
        # fitparse raises FitParseError, but a truncated file can surface as
        # struct.error or IndexError. A corrupt file is expected input here.
        raise UnusableActivity(f'unreadable FIT: {e}') from e

    lat, lon, ele, times, dist, hr, cad, watts = [], [], [], [], [], [], [], []
    for values in records:
        raw_lat = _first(values, 'position_lat')
        raw_lon = _first(values, 'position_long')
        timestamp = values.get('timestamp')
        if raw_lat is None or raw_lon is None or timestamp is None:
            continue  # indoor sample or a lost fix
        lat.append(raw_lat * SEMICIRCLES_TO_DEGREES)
        lon.append(raw_lon * SEMICIRCLES_TO_DEGREES)
        # fitparse returns naive datetimes; the FIT epoch is UTC.
        times.append(timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc))
        ele.append(_first(values, 'enhanced_altitude', 'altitude'))
        dist.append(values.get('distance'))
        hr.append(values.get('heart_rate'))
        cad.append(values.get('cadence'))
        watts.append(values.get('power'))

    if len(lat) < 2:
        raise UnusableActivity('FIT has no GPS records')

    session = sessions[0] if sessions else {}
    if any(d is None for d in dist):
        dist = None  # partial sensor distance is worse than a clean haversine

    streams = derive_streams(
        lat=lat, lon=lon, ele=ele, time=times, distance=dist,
        heartrate=hr if any(v is not None for v in hr) else None,
        cadence=cad if any(v is not None for v in cad) else None,
        watts=watts if any(v is not None for v in watts) else None,
    )
    totals = summarize(streams)
    # The device's own totals beat anything read back off the streams: they
    # include the samples we dropped for having no GPS fix.
    for key, field, cast in (('distance_m', 'total_distance', float),
                             ('elapsed_time_s', 'total_elapsed_time', int),
                             ('moving_time_s', 'total_timer_time', int),
                             ('elevation_gain_m', 'total_ascent', float)):
        value = session.get(field)
        if value is not None:
            totals[key] = cast(value)

    return NormalizedActivity(
        source='upload_fit',
        external_id=content_id(data),
        name=activity_name(filename, session.get('sport_profile_name')),
        start_date=times[0],
        streams=streams,
        sport_type=map_sport(session.get('sport'), session.get('sub_sport')),
        **totals,
    )

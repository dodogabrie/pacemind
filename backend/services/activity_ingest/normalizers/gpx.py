"""GPX file -> NormalizedActivity.

The lossiest of the three file formats: coordinates, elevation and timestamps
only. Distance and velocity are derived by `derive_streams()` — never here, see
the warning at the top of services/activity_ingest/streams.py.
"""

from datetime import timezone

import gpxpy

from services.activity_ingest import NormalizedActivity
from services.activity_ingest.streams import derive_streams
from services.activity_ingest.normalizers import (
    UnusableActivity, activity_name, content_id, map_sport, reject_xml_bombs,
    summarize)


def _wall_clock(t):
    offset = t.utcoffset() if t.tzinfo else None
    return t.replace(tzinfo=None) if offset else None


def normalize_gpx(data: bytes, filename: str = '') -> NormalizedActivity:
    """Parse a GPX activity export into a NormalizedActivity."""
    reject_xml_bombs(data)
    try:
        gpx = gpxpy.parse(data.decode('utf-8', errors='replace'))
    except Exception as e:  # gpxpy raises GPXException and ElementTree errors
        raise UnusableActivity(f'unreadable GPX: {e}') from e

    lat, lon, ele, times = [], [], [], []
    name, sport = None, None
    for track in gpx.tracks:
        name = name or track.name
        sport = sport or track.type
        for segment in track.segments:
            for p in segment.points:
                lat.append(p.latitude)
                lon.append(p.longitude)
                ele.append(p.elevation)
                times.append(p.time)

    if len(lat) < 2:
        raise UnusableActivity('GPX has no usable track points')
    if any(t is None for t in times):
        # A route/course file, not a recording. Those belong to /api/gpx/upload.
        raise UnusableActivity('GPX has no timestamps (route file, not an activity)')

    start = times[0]
    start = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)

    streams = derive_streams(lat=lat, lon=lon, ele=ele, time=times)
    totals = summarize(streams)
    return NormalizedActivity(
        source='upload_gpx',
        external_id=content_id(data),
        name=activity_name(filename, name),
        start_date=start,
        streams=streams,
        sport_type=map_sport(sport),
        # If the file carries a real UTC offset, that IS the wall clock and it
        # beats guessing from longitude. Most exports write 'Z' (offset 0),
        # which says nothing about where the runner was — fall through then.
        start_date_local=_wall_clock(times[0]),
        **totals,
    )

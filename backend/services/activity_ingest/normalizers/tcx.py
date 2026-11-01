"""TCX file -> NormalizedActivity.

Polar, Garmin Connect and COROS all export TCX. It sits between GPX and FIT:
every trackpoint carries cumulative distance and heart rate, but the speed is
still ours to derive. stdlib ElementTree, no lxml — see `reject_xml_bombs` for
why that is safe enough here.
"""

from datetime import datetime, timezone
from xml.etree import ElementTree

from services.activity_ingest import NormalizedActivity
from services.activity_ingest.streams import derive_streams
from services.activity_ingest.normalizers import (
    UnusableActivity, activity_name, content_id, map_sport, reject_xml_bombs,
    summarize)

TCX_NS = '{http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2}'
EXT_NS = '{http://www.garmin.com/xmlschemas/ActivityExtension/v2}'


def _text(node, *path):
    """Text of a nested child, or None. Namespaces prefixed for us."""
    for tag in path:
        if node is None:
            return None
        node = node.find(TCX_NS + tag)
    return node.text if node is not None else None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_tcx(data: bytes, filename: str = '') -> NormalizedActivity:
    """Parse a TCX activity export into a NormalizedActivity."""
    reject_xml_bombs(data)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as e:
        raise UnusableActivity(f'unreadable TCX: {e}') from e

    activity = root.find(f'{TCX_NS}Activities/{TCX_NS}Activity')
    if activity is None:
        raise UnusableActivity('TCX contains no Activity')
    sport = map_sport(activity.get('Sport'))

    lat, lon, ele, times, dist, hr, cad, watts = [], [], [], [], [], [], [], []
    for point in activity.iter(f'{TCX_NS}Trackpoint'):
        plat = _float(_text(point, 'Position', 'LatitudeDegrees'))
        plon = _float(_text(point, 'Position', 'LongitudeDegrees'))
        ptime = _parse_time(_text(point, 'Time'))
        if plat is None or plon is None or ptime is None:
            # Indoor / paused samples: no fix, nothing to place on a map.
            continue
        lat.append(plat)
        lon.append(plon)
        times.append(ptime)
        ele.append(_float(_text(point, 'AltitudeMeters')))
        dist.append(_float(_text(point, 'DistanceMeters')))
        hr.append(_float(_text(point, 'HeartRateBpm', 'Value')))
        cad.append(_float(_text(point, 'Cadence')))
        tpx = point.find(f'{TCX_NS}Extensions/{EXT_NS}TPX')
        w = tpx.find(f'{EXT_NS}Watts') if tpx is not None else None
        watts.append(_float(w.text) if w is not None else None)

    if len(lat) < 2:
        raise UnusableActivity('TCX has no GPS trackpoints')
    if any(d is None for d in dist):
        dist = None  # let derive_streams fall back to haversine

    streams = derive_streams(
        lat=lat, lon=lon, ele=ele, time=times, distance=dist,
        heartrate=hr if any(v is not None for v in hr) else None,
        cadence=cad if any(v is not None for v in cad) else None,
        watts=watts if any(v is not None for v in watts) else None,
    )
    totals = summarize(streams)
    return NormalizedActivity(
        source='upload_tcx',
        external_id=content_id(data),
        name=activity_name(filename, _text(activity, 'Notes')),
        start_date=times[0],
        streams=streams,
        sport_type=sport,
        **totals,
    )

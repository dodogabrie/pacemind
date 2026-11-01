"""One module per source; each exposes a function returning NormalizedActivity.

File-backed sources (`fit`, `tcx`, `gpx`) all take the same shape —
``normalize_x(data: bytes, filename: str) -> NormalizedActivity`` — so the
import job can dispatch on extension alone. They share the small helpers below
rather than each inventing their own summary/sport/identity rules.
"""

import hashlib
import re
from typing import Optional

import numpy as np


class UnusableActivity(Exception):
    """This file is not an activity we can use (no GPS fix, no track, ...).

    Distinct from a parse error only in the message the user gets; the import
    job treats both as "skipped, keep going".
    """


# Only these feed the model. Cycling and swimming from the same export must be
# skipped, not averaged into training load.
RUNNING_SPORTS = {'run', 'trail_run', 'hike'}

# Vendor sport vocabularies are a mess; match on substrings, lowercased.
_SPORT_PATTERNS = (
    ('trail_run', ('trail',)),
    ('run', ('run', 'jog')),
    ('hike', ('hike', 'walk', 'hiking', 'walking', 'trekking')),
)


def map_sport(raw: Optional[str], sub_sport: Optional[str] = None) -> Optional[str]:
    """Vendor sport string -> our vocabulary. None when the file says nothing.

    None means "unknown", and unknown is *allowed* through the sport filter: a
    bare GPX often carries no type at all, and refusing those would reject the
    most common single-file upload.
    """
    if not raw:
        return None
    text = f'{raw} {sub_sport or ""}'.lower()
    for sport, needles in _SPORT_PATTERNS:
        if any(n in text for n in needles):
            return sport
    return 'other'


def is_supported_sport(sport: Optional[str]) -> bool:
    return sport is None or sport in RUNNING_SPORTS


def content_id(data: bytes) -> str:
    """Stable id for an uploaded file: the hash of its bytes.

    Uploads have no provider id, so the content is the identity — re-dropping
    the same archive hits the (source, external_id) unique constraint and
    updates the existing row instead of creating a second one.
    """
    return hashlib.sha256(data).hexdigest()[:32]


def activity_name(filename: str, given: Optional[str] = None) -> str:
    if given and given.strip():
        return given.strip()[:255]
    stem = re.sub(r'\.(gz|fit|tcx|gpx)$', '', (filename or '').rsplit('/', 1)[-1],
                  flags=re.IGNORECASE)
    stem = re.sub(r'\.(gz|fit|tcx|gpx)$', '', stem, flags=re.IGNORECASE)
    return (stem or 'Imported activity')[:255]


def summarize(streams: dict) -> dict:
    """Totals the Activity row needs, read back off the canonical streams.

    Derived here rather than trusting per-vendor summary fields so that a FIT
    session record and a GPX track end up measured the same way — except for
    distance, where the file's own total is better when it exists (see the FIT
    normalizer) and the caller overrides it.
    """
    distance = streams.get('distance') or []
    time = streams.get('time') or []
    altitude = streams.get('altitude') or []
    moving = streams.get('moving') or []

    elapsed = int(time[-1] - time[0]) if len(time) >= 2 else None
    moving_s = None
    if elapsed is not None and len(moving) == len(time):
        # Each sample owns the interval that ends at it.
        moving_s = int(sum(time[i] - time[i - 1]
                           for i in range(1, len(time)) if moving[i]))

    gain = None
    if len(altitude) >= 2:
        gain = float(np.clip(np.diff(np.asarray(altitude, dtype=float)), 0, None).sum())

    return {
        'distance_m': float(distance[-1]) if distance else 0.0,
        'elapsed_time_s': elapsed,
        'moving_time_s': moving_s,
        'elevation_gain_m': gain,
    }


def reject_xml_bombs(data: bytes) -> None:
    """Refuse XML that declares a DTD.

    stdlib ElementTree (and therefore gpxpy) is documented as vulnerable to
    entity-expansion attacks — "billion laughs" — and `defusedxml` is not a
    dependency we are spending this phase's budget on. No legitimate GPX or TCX
    export from any vendor carries a DOCTYPE, so refusing them costs nothing
    and removes the whole class.
    """
    head = data[:4096].lstrip()
    if b'<!DOCTYPE' in head.upper() or b'<!ENTITY' in data[:4096].upper():
        raise UnusableActivity('XML declares a DTD; refused')

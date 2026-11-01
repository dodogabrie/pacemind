"""Timezone helpers for values that round-trip through the database.

Most datetime columns in this codebase are plain ``db.DateTime``
(``TIMESTAMP WITHOUT TIME ZONE`` in Postgres). Their Python-side defaults are
timezone-aware — ``datetime.now(timezone.utc)`` — but Postgres stores those
stripped of tzinfo and hands them back *naive*. Subtracting a naive value from
an aware ``datetime.now(timezone.utc)`` raises:

    TypeError: can't subtract offset-naive and offset-aware datetimes

which is how the Strava activity-list cache broke: every read of an existing
cache row raised, `/api/strava/activities` returned 500, and the Training page
could not load activities at all.

Values are written as UTC, so interpreting a naive value as UTC is correct.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return ``value`` as a timezone-aware UTC datetime.

    A naive value is assumed to already be UTC (that is what we store), and an
    aware one is converted. ``None`` passes through so callers can keep their
    own null handling.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    """Timezone-aware 'now', for symmetry with :func:`as_utc` at call sites."""
    return datetime.now(timezone.utc)


def local_wall_clock(value: Optional[datetime], lon: Optional[float] = None) -> Optional[datetime]:
    """Naive local wall-clock time at longitude ``lon`` for a UTC instant.

    Used to derive the calendar day an activity belongs to: training load and
    plan compliance bucket by day, and a 22:00 local run bucketed by its UTC
    date lands on the wrong day — and, at a week boundary, in the wrong week.

    TODO(multi-source #84 — see GH issues): approximate offset, no tz database.
    ponytail: longitude/15 instead of a real tz database. It is exact for zones
    on their geographic meridian and off by at most an hour or two for the
    political outliers (Spain, China, most of Argentina) and for DST, which
    only matters for activities starting within that margin of midnight.
    Upgrade path: add `timezonefinder` and look up the real zone — deliberately
    not done here because phase 2's budget is one new dependency and it went to
    the FIT parser.
    """
    if value is None:
        return None
    value = as_utc(value)
    if lon is None:
        return value.replace(tzinfo=None)
    return (value + timedelta(hours=round(lon / 15.0))).replace(tzinfo=None)

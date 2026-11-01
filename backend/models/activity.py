"""An activity — a recorded session from any source, not just Strava.

Evolved in place from `strava_activities` (see
docs/plans/multi-source-activities/02-activity-abstraction.md): the table was
renamed rather than replaced, so every existing row and FK survives and
`StravaActivity` stays importable as an alias.

`source` + `external_id` identify the provider's record; `dedup_key` identifies
the *session* independently of who reported it, so the same run arriving from
Strava and from a Garmin FIT collapses onto one row.
"""

import hashlib
import math

from sqlalchemy import false as sa_false

from database import db
from datetime import datetime, timezone

from utils.datetime_utils import as_utc

# Which source wins when the same session arrives twice. The device's own FIT
# has sensor-derived distance and velocity; Strava re-processes it; GPX is the
# lossiest. Higher number replaces the streams, lower number only links its id.
SOURCE_PRECEDENCE = {
    'upload_gpx': 10,
    'upload_tcx': 15,  # distance + HR per trackpoint, but still no sensor speed
    'strava': 20,
    'upload_fit': 30,
    'garmin': 40,
}


# How much two records of the same session may disagree before we call them
# different sessions. Distance tolerance is *relative* because a watch and a
# provider's re-processing diverge more over an ultra than over a 5k.
DEDUP_TIME_TOLERANCE_S = 120.0
DEDUP_DISTANCE_TOLERANCE_M = 50.0
DEDUP_DISTANCE_TOLERANCE_FRAC = 0.005

_MINUTE_BUCKET_S = 60.0
_DISTANCE_BUCKET_M = 50.0


def _dedup_key(user_id: int, minute_bucket: int, distance_bucket: int) -> str:
    raw = f"{user_id}|{minute_bucket}|{distance_bucket}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def _buckets(user_id: int, start_date: datetime, distance_m: float):
    start_ts = as_utc(start_date).timestamp()
    return (round(start_ts / _MINUTE_BUCKET_S),
            round((distance_m or 0) / _DISTANCE_BUCKET_M))


def make_dedup_key(user_id: int, start_date: datetime, distance_m: float) -> str:
    """Content key for a session: user + minute-bucketed start + 50m distance.

    The stored key is only the *fast path*. `round()` gives exact buckets, not
    a tolerance, so two records of the same session that straddle a bucket edge
    hash differently (multi-source #83). Lookups therefore go through
    :func:`dedup_candidate_keys` + :func:`is_same_session`, which probe the
    neighbouring buckets and then compare the real start time and distance.
    The stored format is unchanged, so nothing needs re-backfilling — including
    the inlined copy in migrations/versions/p1a2b3c4d5f5_*.py.
    """
    minute, dist = _buckets(user_id, start_date, distance_m)
    return _dedup_key(user_id, minute, dist)


# The probe must reach at least as far as the tolerance, or the bucket width
# silently becomes the tolerance. Bounded so an ultra does not generate an
# unbounded IN() list.
# ponytail: a range query on (user_id, start_date) would need no enumeration at
# all — ix_strava_activity_user_date already supports it. Kept as key probes
# because they hit the dedup index directly; switch if the key list ever
# stops being small.
MAX_DISTANCE_BUCKET_PROBE = 20  # +/- 1 km


def dedup_candidate_keys(user_id: int, start_date: datetime,
                         distance_m: float) -> list:
    """Every key a same-session row could carry, exact bucket first.

    A handful of indexed point lookups against `ix_activity_user_dedup` — still
    O(1) in table size — turning the exact bucket into a real +/-tolerance
    probe. Candidates are then confirmed by :func:`is_same_session`; the probe
    is deliberately wider than the accepted tolerance so a row on a boundary is
    never missed.
    """
    minute, dist = _buckets(user_id, start_date, distance_m)
    reach = max(DEDUP_DISTANCE_TOLERANCE_M,
                DEDUP_DISTANCE_TOLERANCE_FRAC * (distance_m or 0))
    span_d = min(math.ceil(reach / _DISTANCE_BUCKET_M), MAX_DISTANCE_BUCKET_PROBE)
    span_t = math.ceil(DEDUP_TIME_TOLERANCE_S / _MINUTE_BUCKET_S)
    offsets_t = sorted(range(-span_t, span_t + 1), key=abs)
    offsets_d = sorted(range(-span_d, span_d + 1), key=abs)
    return [_dedup_key(user_id, minute + dt, dist + dd)
            for dt in offsets_t for dd in offsets_d]


def is_same_session(activity, start_date: datetime, distance_m: float) -> bool:
    """Do the actual start time and distance agree within tolerance?"""
    delta_s = abs((as_utc(activity.start_date) - as_utc(start_date)).total_seconds())
    if delta_s > DEDUP_TIME_TOLERANCE_S:
        return False
    distance_m = distance_m or 0
    tolerance = max(DEDUP_DISTANCE_TOLERANCE_M,
                    DEDUP_DISTANCE_TOLERANCE_FRAC * max(distance_m, activity.distance or 0))
    return abs((activity.distance or 0) - distance_m) <= tolerance


class Activity(db.Model):
    """A recorded activity from any source."""
    __tablename__ = 'activities'
    __table_args__ = (
        db.Index('ix_strava_activity_user_date', 'user_id', 'start_date'),
        db.Index('ix_activity_user_dedup', 'user_id', 'dedup_key'),
        db.UniqueConstraint('user_id', 'source', 'external_id',
                            name='uq_activity_user_source_external'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    source = db.Column(db.String(32), nullable=False, default='strava',
                       server_default='strava')
    external_id = db.Column(db.String(128), nullable=True)  # provider id, or content hash for uploads
    dedup_key = db.Column(db.String(64), nullable=True)

    # Kept for Strava rows and every existing caller. Nullable now: a FIT or
    # GPX upload has no Strava id.
    strava_id = db.Column(db.BigInteger, nullable=True)

    name = db.Column(db.String(255), nullable=False)
    distance = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    # Wall-clock time where the activity happened. Naive on purpose: it is a
    # calendar reading, not an instant. Training load and plan compliance
    # bucket by day, and bucketing a 22:00 local run by its UTC date shifts it
    # into the next day and with it a whole week of ATL/CTL.
    start_date_local = db.Column(db.DateTime, nullable=True)

    sport_type = db.Column(db.String(32), nullable=True)  # run / trail_run / hike / other
    moving_time_s = db.Column(db.Integer, nullable=True)
    elapsed_time_s = db.Column(db.Integer, nullable=True)
    elevation_gain_m = db.Column(db.Float, nullable=True)

    # Race flag (pred-review #96). race_source: 'strava_flag' (workout_type 1)
    # or 'user' (confirmed/rejected in the UI; wins over Strava); NULL means
    # nobody decided, so the detector (services/race_detection_service.py)
    # may still propose it. Detections are computed live, never stored.
    is_race = db.Column(db.Boolean, nullable=False, default=False, server_default=sa_false())
    race_source = db.Column(db.String(16), nullable=True)
    start_lat = db.Column(db.Float, nullable=True)
    start_lng = db.Column(db.Float, nullable=True)

    # Streams stored as JSON. none_as_null: a summary row (no streams) must be
    # SQL NULL, not JSON 'null', or `_streams.isnot(None)` counts it as having streams.
    _streams = db.Column('streams', db.JSON(none_as_null=True), nullable=True)

    downloaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def streams(self):
        """Get streams data."""
        return self._streams

    @streams.setter
    def streams(self, value):
        """Store streams data."""
        self._streams = value

    @property
    def local_date(self):
        """Calendar day this activity belongs to, in the runner's local time."""
        return (self.start_date_local or self.start_date).date()

    @property
    def precedence(self) -> int:
        """Rank of this row's source; unknown sources sort below everything."""
        return SOURCE_PRECEDENCE.get(self.source, 0)

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'strava_id': self.strava_id,
            'source': self.source,
            'external_id': self.external_id,
            'name': self.name,
            'distance': self.distance,
            'sport_type': self.sport_type,
            'start_date': self.start_date.isoformat(),
            'has_streams': self._streams is not None,
            'downloaded_at': self.downloaded_at.isoformat() if self.downloaded_at else None
        }

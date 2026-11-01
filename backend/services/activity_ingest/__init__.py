"""The single write path for activities, whatever their source.

Every source normalizes to `NormalizedActivity` and hands it to
`ActivityIngestService.ingest()`, which owns dedup, source precedence, the row
upsert, streams persistence and residual collection. Adding a source is
"write a normalizer", not "touch ten services".

See docs/plans/multi-source-activities/02-activity-abstraction.md.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import Activity
from models.activity import (SOURCE_PRECEDENCE, dedup_candidate_keys,
                            is_same_session, make_dedup_key)
from repositories import ActivityRepository, UserActivityResidualRepository
from services.cache_service import CacheService
from utils.datetime_utils import local_wall_clock

logger = logging.getLogger(__name__)


@dataclass
class NormalizedActivity:
    """What every normalizer returns. Canonical stream keys, see the spec."""
    source: str
    external_id: Optional[str]
    name: str
    start_date: datetime          # tz-aware, UTC
    distance_m: float
    streams: Dict[str, List] = field(default_factory=dict)
    moving_time_s: Optional[int] = None
    elapsed_time_s: Optional[int] = None
    elevation_gain_m: Optional[float] = None
    sport_type: Optional[str] = None
    start_date_local: Optional[datetime] = None   # naive wall clock, derived if absent
    is_race: Optional[bool] = None   # provider's race flag; None = provider has none
    start_lat: Optional[float] = None  # derived from the latlng stream if absent
    start_lng: Optional[float] = None

    def __post_init__(self):
        if self.source not in SOURCE_PRECEDENCE:
            raise ValueError(
                f"unknown activity source {self.source!r}; "
                f"add it to models.activity.SOURCE_PRECEDENCE with its rank"
            )
        if self.start_date is None:
            raise ValueError("normalized activity has no start_date")
        if self.start_date.tzinfo is None:
            self.start_date = self.start_date.replace(tzinfo=timezone.utc)
        if self.external_id is not None:
            self.external_id = str(self.external_id)
        if self.start_date_local is None:
            self.start_date_local = local_wall_clock(self.start_date,
                                                     self._start_longitude())
        latlng = (self.streams or {}).get('latlng') or []
        if self.start_lat is None and latlng and len(latlng[0]) == 2:
            self.start_lat, self.start_lng = float(latlng[0][0]), float(latlng[0][1])
        elif self.start_date_local.tzinfo is not None:
            self.start_date_local = self.start_date_local.replace(tzinfo=None)

    def _start_longitude(self) -> Optional[float]:
        """Longitude of the first GPS fix, for the local-time derivation."""
        latlng = (self.streams or {}).get('latlng') or []
        if latlng and len(latlng[0]) == 2:
            return float(latlng[0][1])
        return None


class ActivityIngestService:
    """Dedup + precedence + upsert + streams + residuals, in one place."""

    def __init__(self, activity_repo=None, residual_repo=None,
                 cache_service=None, residual_service=None):
        self.activity_repo = activity_repo or ActivityRepository()
        self.residual_repo = residual_repo or UserActivityResidualRepository()
        self.cache_service = cache_service or CacheService()
        # Imported lazily: UserResidualService pulls in the whole physics stack.
        self._residual_service = residual_service

    @property
    def residual_service(self):
        if self._residual_service is None:
            from services.user_residual_service import UserResidualService
            self._residual_service = UserResidualService()
        return self._residual_service

    def ingest(self, user_id: int, normalized: NormalizedActivity,
               collect_residuals: bool = True) -> Activity:
        """Create or update the one row for this session. Returns it.

        Does not commit — the caller owns the transaction boundary, as
        everywhere else in this codebase.

        `collect_residuals=False` for callers that only want the row cached
        (see CacheService.cache_streams) and must not change a user's tier as
        a side effect.
        """
        dedup_key = make_dedup_key(user_id, normalized.start_date,
                                   normalized.distance_m)

        existing = None
        if normalized.external_id is not None:
            existing = self.activity_repo.get_by_external_id(
                user_id, normalized.source, normalized.external_id)
        if existing is None:
            existing = self._find_same_session(user_id, normalized, dedup_key)

        if existing is None:
            return self._create(user_id, normalized, dedup_key, collect_residuals)

        # The same provider re-reporting the same record is a refresh, not a
        # duplicate — take the new data regardless of precedence.
        same_record = (existing.source == normalized.source
                       and normalized.external_id is not None
                       and existing.external_id == normalized.external_id)
        promoted = SOURCE_PRECEDENCE.get(normalized.source, 0) > existing.precedence

        if promoted or same_record:
            return self._update(user_id, existing, normalized, dedup_key,
                                promoted=promoted,
                                collect_residuals=collect_residuals)

        # Lower precedence from a different source: keep what we have, just
        # link the incoming id so a later lookup finds this row.
        if normalized.source == 'strava' and existing.strava_id is None:
            existing.strava_id = _as_int(normalized.external_id)
        if existing.dedup_key is None:
            existing.dedup_key = dedup_key
        _apply_race_and_place(existing, normalized)
        if not existing.streams and normalized.streams:
            existing.streams = normalized.streams
            self._persist_streams(user_id, existing, normalized.streams)
        logger.debug(
            f"Activity {existing.id}: kept {existing.source} streams over "
            f"incoming {normalized.source} (lower precedence)")
        return existing

    def _find_same_session(self, user_id, normalized, dedup_key):
        """The row for this session, whichever bucket its key landed in.

        The exact key is the fast path; on a miss we probe the neighbouring
        (minute, distance) buckets, because `round()` is a bucket and not a
        tolerance — the same session recorded twice can straddle an edge
        (multi-source #83). Candidates are confirmed against the real start
        time and distance before we call them the same session.
        """
        exact = self.activity_repo.get_by_dedup_key(user_id, dedup_key)
        if exact is not None:
            return exact
        keys = dedup_candidate_keys(user_id, normalized.start_date,
                                    normalized.distance_m)
        candidates = self.activity_repo.get_by_dedup_keys(user_id, keys[1:])
        for candidate in candidates:
            if is_same_session(candidate, normalized.start_date,
                               normalized.distance_m):
                return candidate
        return None

    # ── internals ────────────────────────────────────────────────────────────

    def _create(self, user_id, normalized, dedup_key, collect_residuals=True) -> Activity:
        activity = Activity(
            user_id=user_id,
            source=normalized.source,
            external_id=normalized.external_id,
            dedup_key=dedup_key,
            strava_id=(_as_int(normalized.external_id)
                       if normalized.source == 'strava' else None),
            name=normalized.name or 'Unnamed Activity',
            distance=normalized.distance_m or 0,
            start_date=normalized.start_date,
            start_date_local=normalized.start_date_local,
            sport_type=normalized.sport_type,
            moving_time_s=normalized.moving_time_s,
            elapsed_time_s=normalized.elapsed_time_s,
            elevation_gain_m=normalized.elevation_gain_m,
        )
        _apply_race_and_place(activity, normalized)
        activity.streams = normalized.streams or None
        self.activity_repo.create(activity)  # flush to get ID
        self._persist_streams(user_id, activity, normalized.streams)
        if collect_residuals:
            self._collect_residuals(user_id, activity, normalized)
        return activity

    def _update(self, user_id, existing, normalized, dedup_key,
                promoted: bool, collect_residuals: bool = True) -> Activity:
        """Take the incoming data. `promoted` = a better source displaced the old one."""
        if promoted:
            logger.info(
                f"Activity {existing.id}: replacing {existing.source} streams "
                f"with {normalized.source} (higher precedence)")

        if normalized.source == 'strava':
            existing.strava_id = _as_int(normalized.external_id)
        existing.source = normalized.source
        existing.external_id = normalized.external_id
        existing.dedup_key = dedup_key
        existing.name = normalized.name or existing.name
        existing.distance = normalized.distance_m or existing.distance
        existing.start_date = normalized.start_date
        existing.start_date_local = normalized.start_date_local
        for attr in ('sport_type', 'moving_time_s', 'elapsed_time_s',
                     'elevation_gain_m'):
            value = getattr(normalized, attr)
            if value is not None:
                setattr(existing, attr, value)
        _apply_race_and_place(existing, normalized)
        if normalized.streams:
            existing.streams = normalized.streams
            existing.downloaded_at = datetime.now(timezone.utc)
            self._persist_streams(user_id, existing, normalized.streams)
            if collect_residuals:
                self._collect_residuals(user_id, existing, normalized,
                                        replace=promoted)
        return existing

    # TODO(multi-source #18 — see GH issues): streams are stored twice (JSON
    # column + this filesystem mirror) with no retention, compression or size
    # policy. Bulk file import removes the old 50-activities-per-sync ceiling,
    # so this is now unbounded per user. Measure per-activity size and decide a
    # downsample/evict policy before the "import your history" CTA ships.
    def _persist_streams(self, user_id, activity, streams):
        """Filesystem mirror of the streams, via the existing cache paths."""
        if not streams:
            return
        import json
        key = activity.strava_id or f'{activity.source}_{activity.id}'
        path = self.cache_service.get_stream_cache_path(user_id, key)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(streams, f)
        except OSError as e:
            # The DB copy is authoritative; the filesystem one is a cache.
            logger.warning(f"Could not write stream cache {path}: {e}")

    def _residual_activity_id(self, activity) -> str:
        """Key used by UserActivityResidual.activity_id.

        Strava rows keep the bare Strava id so residuals collected before this
        refactor still match.
        """
        if activity.strava_id:
            return str(activity.strava_id)
        # Row id, not external_id: UserActivityResidual.activity_id is
        # String(50) and an upload's external_id is a content hash.
        return f'{activity.source}_{activity.id}'

    def _collect_residuals(self, user_id, activity, normalized, replace=False):
        if not normalized.streams:
            return
        activity_id = self._residual_activity_id(activity)
        try:
            existing = self.residual_repo.get_by_activity(user_id, activity_id)
            if existing is not None:
                if not replace:
                    return
                self.residual_repo.delete(existing)
            residual = self.residual_service.collect_residuals_from_activity(
                user_id=user_id,
                activity_id=activity_id,
                activity_streams=normalized.streams,
                activity_metadata={
                    'start_date': activity.start_date,
                    'distance': activity.distance,
                    'elevation': normalized.elevation_gain_m or 0,
                },
            )
            if residual is not None:
                residual.source = normalized.source
        except Exception as e:
            # Residual collection is a training-data optimisation, never a
            # reason to lose the activity itself.
            logger.error(f"Error collecting residuals for {activity_id}: {e}")


def _apply_race_and_place(activity, normalized):
    """Provider race flag + start coordinates. The user's own call
    (race_source='user') always wins over the provider's flag."""
    if activity.start_lat is None and normalized.start_lat is not None:
        activity.start_lat, activity.start_lng = normalized.start_lat, normalized.start_lng
    if normalized.is_race is None or activity.race_source == 'user':
        return
    if normalized.is_race:
        activity.is_race, activity.race_source = True, 'strava_flag'
    elif activity.race_source == 'strava_flag':  # un-flagged on Strava since
        activity.is_race, activity.race_source = False, None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


from services.activity_ingest.normalizers.fit import normalize_fit  # noqa: E402
from services.activity_ingest.normalizers.gpx import normalize_gpx  # noqa: E402
from services.activity_ingest.normalizers.strava import normalize_strava  # noqa: E402
from services.activity_ingest.normalizers.tcx import normalize_tcx  # noqa: E402
from services.activity_ingest.streams import derive_streams  # noqa: E402,F401

# Note the two signatures: the file normalizers all take (data: bytes,
# filename: str) so the import job can dispatch on extension alone, while
# 'strava' takes the API payload it already has in hand. Look them up by the
# key you know you have, not by iterating this dict.
NORMALIZERS = {
    'strava': normalize_strava,
    'fit': normalize_fit,
    'tcx': normalize_tcx,
    'gpx': normalize_gpx,
}

__all__ = ['ActivityIngestService', 'NormalizedActivity', 'NORMALIZERS',
           'derive_streams']

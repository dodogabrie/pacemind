"""Cache service for Strava data.

Handles caching of:
- Activity streams (DB + filesystem JSON)
- Activity lists (DB only)
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from utils.datetime_utils import as_utc

from repositories import ActivityRepository, StravaCacheRepository

logger = logging.getLogger(__name__)


class CacheService:
    """Service for managing Strava data cache."""

    def __init__(self, cache_dir='data/strava_cache', activity_repo=None, cache_repo=None):
        """Initialize cache service.

        Args:
            cache_dir: Directory for filesystem cache
            activity_repo: ActivityRepository instance
            cache_repo: StravaCacheRepository instance
        """
        self.activity_repo = activity_repo or ActivityRepository()
        self.cache_repo = cache_repo or StravaCacheRepository()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.streams_dir = self.cache_dir / 'streams'
        self.streams_dir.mkdir(parents=True, exist_ok=True)

    def get_stream_cache_path(self, user_id, activity_id):
        """Get filesystem path for activity stream cache.

        Args:
            user_id: User ID
            activity_id: Strava activity ID

        Returns:
            Path object for the cache file
        """
        user_dir = self.streams_dir / str(user_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir / f'{activity_id}.json'

    def get_cached_streams(self, user_id, activity_id):
        """Get cached streams for an activity.

        Checks both DB and filesystem. Returns None if not found.

        Args:
            user_id: User ID
            activity_id: Strava activity ID

        Returns:
            Streams dict or None if not cached
        """
        # Check database first
        db_activity = self.activity_repo.get_by_strava_id(user_id, activity_id)

        if db_activity and db_activity.streams:
            logger.debug(f"Found streams in DB for activity {activity_id}")
            return db_activity.streams

        # Check filesystem
        cache_path = self.get_stream_cache_path(user_id, activity_id)
        if cache_path.exists():
            logger.debug(f"Found streams in filesystem for activity {activity_id}")
            with open(cache_path, 'r', encoding='utf-8') as f:
                streams = json.load(f)

            # Store in DB for faster access next time
            if db_activity:
                db_activity.streams = streams
                self.activity_repo.commit()
            else:
                logger.warning(f"Filesystem cache exists but no DB entry for activity {activity_id}")

            return streams

        logger.debug(f"No cached streams for activity {activity_id}")
        return None

    def cache_streams(self, user_id, activity_id, activity_name, distance, start_date, streams):
        """Cache Strava activity streams in both DB and filesystem.

        Thin wrapper over ActivityIngestService — the single activity write
        path. Residual collection is deliberately off: this is a cache fill,
        and collecting residuals here would silently move a user's prediction
        tier as a side effect of viewing their performance page.

        Args:
            user_id: User ID
            activity_id: Strava activity ID
            activity_name: Activity name
            distance: Activity distance in meters
            start_date: Activity start date (datetime)
            streams: Streams dict

        Returns:
            Activity object
        """
        from services.activity_ingest import ActivityIngestService
        from services.activity_ingest.normalizers.strava import normalize_strava

        db_activity = ActivityIngestService(
            activity_repo=self.activity_repo, cache_service=self,
        ).ingest(
            user_id,
            normalize_strava({
                'id': activity_id,
                'name': activity_name,
                'distance': distance,
                'start_date': start_date,
            }, streams),
            collect_residuals=False,
        )

        self.activity_repo.commit()
        logger.debug(f"Saved streams to DB for activity {activity_id}")

        return db_activity

    def get_cached_activities(self, user_id, max_age_hours=24):
        """Get cached activity list for user.

        Args:
            user_id: User ID
            max_age_hours: Maximum cache age in hours

        Returns:
            List of activities or None if cache is stale/missing
        """
        cache = self.cache_repo.get_cached(user_id)

        if not cache:
            logger.debug(f"No activity list cache for user {user_id}")
            return None

        if cache.is_stale(max_age_hours):
            logger.debug(f"Activity list cache is stale (age: {(datetime.now(timezone.utc) - as_utc(cache.fetched_at)).total_seconds() / 3600:.1f}h)")
            return None

        logger.debug(f"Using cached activity list ({cache.activity_count} activities, age: {(datetime.now(timezone.utc) - as_utc(cache.fetched_at)).total_seconds() / 3600:.1f}h)")
        return cache.activities

    def cache_activities(self, user_id, activities, after_timestamp=None):
        """Cache activity list for user.

        Args:
            user_id: User ID
            activities: List of activity dicts from Strava API
            after_timestamp: Optional timestamp filter used in query

        Returns:
            StravaActivityCache object
        """
        cache = self.cache_repo.cache_activities(user_id, activities, after_timestamp)
        self.cache_repo.commit()
        logger.debug(f"Cached {len(activities)} activities for user {user_id}")

        return cache

    def clear_stale_caches(self, max_age_hours=168):
        """Clear old caches from database.

        Args:
            max_age_hours: Age threshold in hours (default 7 days)
        """
        from datetime import timedelta

        threshold = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # Clear old activity list caches
        stale_caches = self.cache_repo.get_stale(threshold)
        deleted = len(stale_caches)
        for cache in stale_caches:
            self.cache_repo.delete(cache)

        self.cache_repo.commit()
        logger.debug(f"Cleared {deleted} stale activity list caches")

        return deleted

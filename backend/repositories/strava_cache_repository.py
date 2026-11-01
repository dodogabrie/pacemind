"""Strava activity cache repository."""

from datetime import datetime
from typing import List, Optional
from models import StravaActivityCache
from repositories.base import BaseRepository


class StravaCacheRepository(BaseRepository[StravaActivityCache]):
    model = StravaActivityCache

    def get_cached(self, user_id: int) -> Optional[StravaActivityCache]:
        """Get cached activity list for user."""
        return self.find_one_by(user_id=user_id)

    def cache_activities(self, user_id: int, activities: list,
                          after_timestamp: int = None) -> StravaActivityCache:
        """Store or update cached activity list."""
        cache = self.get_cached(user_id)
        if cache:
            cache.activities = activities
            cache.after_timestamp = after_timestamp
        else:
            cache = StravaActivityCache(user_id=user_id, after_timestamp=after_timestamp)
            cache.activities = activities
            self.create(cache)
        return cache

    def get_stale(self, threshold: datetime) -> List[StravaActivityCache]:
        """Get caches older than the given threshold."""
        return StravaActivityCache.query.filter(
            StravaActivityCache.fetched_at < threshold
        ).all()

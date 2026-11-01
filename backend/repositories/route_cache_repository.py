"""Route cache repository — ORS responses keyed by deterministic waypoint hash."""

from typing import Optional
from datetime import datetime, timezone
from models.route_cache import RouteCache
from repositories.base import BaseRepository


class RouteCacheRepository(BaseRepository[RouteCache]):
    model = RouteCache

    def get_cached(self, cache_key: str) -> Optional[dict]:
        """Return cached route data if present and unexpired; bumps hit counter."""
        entry = self.find_one_by(cache_key=cache_key)
        if not entry:
            return None
        if entry.expires_at <= datetime.now(timezone.utc):
            return None
        entry.hits = (entry.hits or 0) + 1
        self.flush()
        return entry.data

    def set_cached(self, cache_key: str, data: dict, expires_at: datetime) -> RouteCache:
        entry = self.find_one_by(cache_key=cache_key)
        if entry:
            entry.data = data
            entry.expires_at = expires_at
        else:
            entry = RouteCache(
                cache_key=cache_key,
                data=data,
                expires_at=expires_at,
                hits=0,
            )
            self.create(entry)
        return entry

    def cleanup_expired(self) -> int:
        expired = RouteCache.query.filter(
            RouteCache.expires_at < datetime.now(timezone.utc)
        ).all()
        count = len(expired)
        for entry in expired:
            self.delete(entry)
        return count

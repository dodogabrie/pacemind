"""Weather cache repository."""

from typing import Optional
from datetime import datetime, timezone
from models import WeatherCache
from repositories.base import BaseRepository


class WeatherCacheRepository(BaseRepository[WeatherCache]):
    model = WeatherCache

    def get_cached(self, cache_key: str) -> Optional[dict]:
        """Get cached weather data if not expired."""
        entry = self.find_one_by(cache_key=cache_key)
        if entry and entry.expires_at and entry.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            return entry.data
        return None

    def set_cached(self, cache_key: str, data: dict, cache_type: str,
                    expires_at: datetime) -> WeatherCache:
        """Store or update cached weather data."""
        entry = self.find_one_by(cache_key=cache_key)
        if entry:
            entry.data = data
            entry.cache_type = cache_type
            entry.expires_at = expires_at
        else:
            entry = WeatherCache(
                cache_key=cache_key, data=data,
                cache_type=cache_type, expires_at=expires_at
            )
            self.create(entry)
        return entry

    def cleanup_expired(self) -> int:
        """Delete expired cache entries. Returns count deleted."""
        expired = WeatherCache.query.filter(
            WeatherCache.expires_at < datetime.now(timezone.utc)
        ).all()
        count = len(expired)
        for entry in expired:
            self.delete(entry)
        return count

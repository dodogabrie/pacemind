"""Terrain cache repository."""

from typing import Optional
from datetime import datetime, timezone
from models import TerrainCache
from repositories.base import BaseRepository


class TerrainCacheRepository(BaseRepository[TerrainCache]):
    model = TerrainCache

    def get_cached(self, cache_key: str) -> Optional[dict]:
        """Get cached terrain data if not expired."""
        entry = self.find_one_by(cache_key=cache_key)
        if entry and entry.expires_at > datetime.now(timezone.utc):
            return entry.data
        return None

    def set_cached(self, cache_key: str, data: dict, expires_at: datetime) -> TerrainCache:
        """Store or update cached terrain data."""
        entry = self.find_one_by(cache_key=cache_key)
        if entry:
            entry.data = data
            entry.expires_at = expires_at
        else:
            entry = TerrainCache(
                cache_key=cache_key, data=data, expires_at=expires_at
            )
            self.create(entry)
        return entry

    def cleanup_expired(self) -> int:
        """Delete expired cache entries. Returns count deleted."""
        expired = TerrainCache.query.filter(
            TerrainCache.expires_at < datetime.now(timezone.utc)
        ).all()
        count = len(expired)
        for entry in expired:
            self.delete(entry)
        return count

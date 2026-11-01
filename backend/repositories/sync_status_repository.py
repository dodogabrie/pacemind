"""Sync status repository."""

from typing import Optional
from models import SyncStatus
from repositories.base import BaseRepository


class SyncStatusRepository(BaseRepository[SyncStatus]):
    model = SyncStatus

    def get_for_user(self, user_id: int, provider: str = 'strava') -> Optional[SyncStatus]:
        return self.find_one_by(user_id=user_id, provider=provider)

    def get_or_create(self, user_id: int, provider: str = 'strava') -> SyncStatus:
        """Get existing sync status or create new one."""
        status = self.get_for_user(user_id, provider)
        if not status:
            status = SyncStatus(user_id=user_id, provider=provider, status='idle')
            self.create(status)
        return status

    def update_progress(self, status: SyncStatus, **kwargs) -> None:
        """Update sync progress fields."""
        for key, value in kwargs.items():
            if hasattr(status, key):
                setattr(status, key, value)

"""User connection repository (external providers: strava, garmin, …)."""

from typing import Optional
from models import UserConnection
from repositories.base import BaseRepository


class UserConnectionRepository(BaseRepository[UserConnection]):
    model = UserConnection

    def get_by_external_id(self, provider: str, external_user_id: str) -> Optional[UserConnection]:
        return self.find_one_by(provider=provider, external_user_id=str(external_user_id))

    def get_for_user(self, user_id: int, provider: str) -> Optional[UserConnection]:
        return self.find_one_by(user_id=user_id, provider=provider)

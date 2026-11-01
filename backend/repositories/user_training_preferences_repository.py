"""User training preferences repository."""

from typing import Optional
from models import UserTrainingPreferences
from repositories.base import BaseRepository


class UserTrainingPreferencesRepository(BaseRepository[UserTrainingPreferences]):
    model = UserTrainingPreferences

    def get_by_user(self, user_id: int) -> Optional[UserTrainingPreferences]:
        return self.find_one_by(user_id=user_id)

    def upsert(self, user_id: int, data: dict) -> UserTrainingPreferences:
        """Create or update training preferences for user."""
        prefs = self.get_by_user(user_id)
        if prefs:
            for key, value in data.items():
                if hasattr(prefs, key) and key not in ('id', 'user_id', 'created_at', 'updated_at'):
                    setattr(prefs, key, value)
        else:
            prefs = UserTrainingPreferences(user_id=user_id, **data)
            self.create(prefs)
        return prefs

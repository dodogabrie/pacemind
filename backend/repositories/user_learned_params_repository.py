"""User learned params repository."""

from typing import Optional
from models import UserLearnedParams
from repositories.base import BaseRepository


class UserLearnedParamsRepository(BaseRepository[UserLearnedParams]):
    model = UserLearnedParams

    def get_for_user(self, user_id: int) -> Optional[UserLearnedParams]:
        return self.find_one_by(user_id=user_id)

    def save_params(self, user_id: int, **params) -> UserLearnedParams:
        """Create or update learned params for user."""
        learned = self.get_for_user(user_id)
        if learned:
            for key, value in params.items():
                if hasattr(learned, key):
                    setattr(learned, key, value)
        else:
            learned = UserLearnedParams(user_id=user_id, **params)
            self.create(learned)
        return learned

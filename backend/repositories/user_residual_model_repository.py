"""User residual model repository."""

from typing import Optional
from models import UserResidualModel
from repositories.base import BaseRepository


class UserResidualModelRepository(BaseRepository[UserResidualModel]):
    model = UserResidualModel

    def get_for_user(self, user_id: int) -> Optional[UserResidualModel]:
        return self.find_one_by(user_id=user_id)

    def save_model(self, user_id: int, **kwargs) -> UserResidualModel:
        """Create or update residual model for user."""
        model = self.get_for_user(user_id)
        if model:
            for key, value in kwargs.items():
                if hasattr(model, key):
                    setattr(model, key, value)
        else:
            model = UserResidualModel(user_id=user_id, **kwargs)
            self.create(model)
        return model

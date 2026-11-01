"""User activity residual repository."""

from typing import Optional, List
from models import UserActivityResidual
from repositories.base import BaseRepository


class UserActivityResidualRepository(BaseRepository[UserActivityResidual]):
    model = UserActivityResidual

    def get_user_residuals(self, user_id: int) -> List[UserActivityResidual]:
        """Get all residuals for user, newest first."""
        return UserActivityResidual.query.filter_by(user_id=user_id) \
            .order_by(UserActivityResidual.activity_date.desc()).all()

    def get_user_residual(self, residual_id: int, user_id: int) -> Optional[UserActivityResidual]:
        """Get specific residual belonging to user."""
        return self.find_one_by(id=residual_id, user_id=user_id)

    def count_for_user(self, user_id: int) -> int:
        return self.count(user_id=user_id)

    def get_by_activity(self, user_id: int, activity_id: str) -> Optional[UserActivityResidual]:
        """Check if residual exists for a specific activity."""
        return self.find_one_by(user_id=user_id, activity_id=activity_id)

    def get_training_data(self, user_id: int) -> List[UserActivityResidual]:
        """Get non-excluded residuals for ML training."""
        return UserActivityResidual.query.filter_by(
            user_id=user_id, excluded_from_training=False
        ).order_by(UserActivityResidual.activity_date.desc()).all()

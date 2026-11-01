"""User achievement repository."""

from typing import Optional, List
from models import UserAchievement
from repositories.base import BaseRepository


class AchievementRepository(BaseRepository[UserAchievement]):
    model = UserAchievement

    def get_unnotified(self, user_id: int) -> List[UserAchievement]:
        """Get achievements that haven't been notified yet."""
        return UserAchievement.query.filter_by(
            user_id=user_id, notified=False
        ).order_by(UserAchievement.earned_at.desc()).all()

    def find_existing(self, user_id: int, achievement_type: str,
                       achievement_name: str) -> Optional[UserAchievement]:
        """Check if achievement already exists."""
        return self.find_one_by(
            user_id=user_id,
            achievement_type=achievement_type,
            achievement_name=achievement_name
        )

    def mark_notified(self, achievements: List[UserAchievement]) -> None:
        """Mark achievements as notified."""
        for a in achievements:
            a.notified = True

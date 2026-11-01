"""Evaluation status repository."""

from typing import Optional
from models import EvaluationStatus
from repositories.base import BaseRepository


class EvaluationStatusRepository(BaseRepository[EvaluationStatus]):
    model = EvaluationStatus

    def get_for_user(self, user_id: int) -> Optional[EvaluationStatus]:
        return self.find_one_by(user_id=user_id)

    def get_or_create(self, user_id: int) -> EvaluationStatus:
        """Get existing status or create new one."""
        status = self.get_for_user(user_id)
        if not status:
            status = EvaluationStatus(user_id=user_id)
            self.create(status)
        return status

    def update_progress(self, status: EvaluationStatus, **kwargs) -> None:
        """Update evaluation progress fields."""
        for key, value in kwargs.items():
            if hasattr(status, key):
                setattr(status, key, value)

    def reset(self, status: EvaluationStatus) -> None:
        """Reset status for new evaluation."""
        status.reset()

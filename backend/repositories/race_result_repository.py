"""Race result repository."""

from typing import Optional, List
from models.race_result import RaceResult
from repositories.base import BaseRepository


class RaceResultRepository(BaseRepository[RaceResult]):
    model = RaceResult

    def get_by_plan(self, plan_id: int, user_id: int) -> Optional[RaceResult]:
        """Get result for a specific plan."""
        return self.find_one_by(plan_id=plan_id, user_id=user_id)

    def get_user_results(self, user_id: int) -> List[RaceResult]:
        """Get all results for user, newest first."""
        return RaceResult.query.filter_by(user_id=user_id) \
            .order_by(RaceResult.created_at.desc()).all()

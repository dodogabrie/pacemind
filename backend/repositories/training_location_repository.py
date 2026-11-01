"""Training location repository."""

from typing import List, Optional
from models.training_location import TrainingLocation
from repositories.base import BaseRepository


class TrainingLocationRepository(BaseRepository[TrainingLocation]):
    model = TrainingLocation

    def get_user_locations(self, user_id: int) -> List[TrainingLocation]:
        return TrainingLocation.query.filter_by(user_id=user_id).order_by(TrainingLocation.id).all()

    def get_user_location(self, location_id: int, user_id: int) -> Optional[TrainingLocation]:
        return self.find_one_by(id=location_id, user_id=user_id)

    def assign_weekdays(self, user_id: int, location: TrainingLocation, weekdays) -> None:
        """Give ``weekdays`` to ``location`` and take them from the user's other places."""
        days = sorted({int(d) for d in weekdays if 0 <= int(d) <= 6})
        for other in self.get_user_locations(user_id):
            if other.id != location.id and set(other.weekdays or []) & set(days):
                other.weekdays = [d for d in other.weekdays if d not in days]
        location.weekdays = days

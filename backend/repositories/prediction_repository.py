"""Prediction repository."""

from typing import Optional, List
from models import Prediction
from repositories.base import BaseRepository


class PredictionRepository(BaseRepository[Prediction]):
    model = Prediction

    def get_user_prediction(self, prediction_id: int, user_id: int) -> Optional[Prediction]:
        """Get a specific prediction belonging to user."""
        return self.find_one_by(id=prediction_id, user_id=user_id)

    def get_latest_for_gpx(self, gpx_file_id: int, user_id: int) -> Optional[Prediction]:
        """Get the latest prediction for a GPX file belonging to user."""
        return Prediction.query.filter_by(gpx_file_id=gpx_file_id, user_id=user_id) \
            .order_by(Prediction.created_at.desc()).first()

    def get_user_predictions(self, user_id: int, limit: int = None) -> List[Prediction]:
        """Get predictions for user, newest first."""
        q = Prediction.query.filter_by(user_id=user_id) \
            .order_by(Prediction.created_at.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

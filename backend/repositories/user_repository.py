"""User repository."""

from typing import Optional
from models import User
from repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_strava_id(self, strava_user_id: int) -> Optional[User]:
        return self.find_one_by(strava_user_id=strava_user_id)

    def find_or_create_from_strava(self, athlete: dict) -> User:
        """Find existing user by Strava ID or create new one.

        Thin wrapper: the identity rules now live in ConnectionService, which
        also creates the matching `user_connections` row. Kept so existing
        callers keep working; drop once they all use ConnectionService.
        """
        from services.connection_service import ConnectionService
        return ConnectionService().find_or_create_from_strava(athlete)

    def update_tokens(self, user: User, token_data: dict) -> None:
        """Update Strava OAuth tokens."""
        user.access_token = token_data['access_token']
        user.refresh_token = token_data['refresh_token']
        user.expires_at = token_data['expires_at']

    def update_calibration(self, user: User, flat_pace: float,
                           anchor_ratios: dict = None,
                           calibration_activity_id: str = None) -> None:
        """Update user calibration data."""
        user.saved_flat_pace = float(flat_pace)
        if anchor_ratios is not None:
            user.saved_anchor_ratios = anchor_ratios
        if calibration_activity_id is not None:
            user.calibration_activity_id = calibration_activity_id

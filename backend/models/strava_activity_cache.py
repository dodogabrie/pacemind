"""Strava activity list cache model."""

from database import db
from datetime import datetime, timezone

from utils.datetime_utils import as_utc


class StravaActivityCache(db.Model):
    """Cache for user's activity list from Strava.

    Stores snapshots of activity lists to avoid repeated API calls.
    Cache is considered stale after 24 hours.
    """
    __tablename__ = 'strava_activity_cache'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Activity list stored as JSON
    _activities = db.Column('activities', db.JSON, nullable=False)

    # Cache metadata
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    after_timestamp = db.Column(db.Integer, nullable=True)  # Query parameter used
    activity_count = db.Column(db.Integer, nullable=False)

    @property
    def activities(self):
        """Get activities list."""
        if self._activities:
            return self._activities
        return []

    @activities.setter
    def activities(self, value):
        """Store activities list."""
        if value:
            self._activities = value
            self.activity_count = len(value)
        else:
            self._activities = []
            self.activity_count = 0

    def is_stale(self, max_age_hours=24):
        """Check if cache is stale.

        Args:
            max_age_hours: Maximum age in hours before cache is considered stale

        Returns:
            True if cache is older than max_age_hours
        """
        # fetched_at is a naive DB column; interpret it as the UTC it was
        # written as, or this raises on every cached read. See utils/datetime_utils.
        age = datetime.now(timezone.utc) - as_utc(self.fetched_at)
        return age.total_seconds() > (max_age_hours * 3600)

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'fetched_at': self.fetched_at.isoformat(),
            'activity_count': self.activity_count,
            'is_stale': self.is_stale()
        }

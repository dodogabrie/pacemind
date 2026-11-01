"""Sync status model for tracking background activity-import progress.

One row per (user, provider) so a Strava sync and a file import can be in
flight at the same time.
"""

from datetime import datetime, timezone

from database import db


class SyncStatus(db.Model):
    """Tracks progress of a background activity import for a user + provider."""
    __tablename__ = 'sync_status'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'provider', name='uq_sync_status_user_provider'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # strava | garmin | upload | ...
    provider = db.Column(db.String(32), nullable=False, default='strava',
                         server_default='strava')

    # Status: idle, syncing, completed, error
    status = db.Column(db.String(50), default='idle', nullable=False)

    # Current step: selecting_activities, downloading_streams, parsing_files,
    # importing, training_tier2, training_tier3
    current_step = db.Column(db.String(100), nullable=True)

    # Progress tracking
    total_activities = db.Column(db.Integer, default=0)
    downloaded_activities = db.Column(db.Integer, default=0)

    # A Strava push event arrived mid-sync: re-run once when this one ends.
    resync_pending = db.Column(db.Boolean, nullable=False, default=False,
                               server_default=db.false())

    # Messages
    message = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # Timestamps
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Convert to dictionary for API response."""
        return {
            'provider': self.provider,
            'status': self.status,
            'current_step': self.current_step,
            'total_activities': self.total_activities,
            'downloaded_activities': self.downloaded_activities,
            'progress_percent': int(self.downloaded_activities / self.total_activities * 100) if self.total_activities > 0 else 0,
            'message': self.message,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }

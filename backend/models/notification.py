"""Notification model for user notifications."""

from database import db
from datetime import datetime, timezone


class Notification(db.Model):
    """Stores notifications for users (compliance summaries, coach suggestions, countdowns)."""
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notification_user_read', 'user_id', 'read', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    type = db.Column(db.String(32), nullable=False)
    # Types: weekly_summary, coach_suggestion, race_countdown

    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    read = db.Column(db.Boolean, default=False, nullable=False)

    # Optional references
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plans.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'read': self.read,
            'plan_id': self.plan_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

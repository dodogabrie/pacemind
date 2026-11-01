"""Notification repository."""

from typing import List
from models import Notification
from repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    def get_unread(self, user_id: int) -> List[Notification]:
        """Get unread notifications for user, newest first."""
        return Notification.query.filter_by(
            user_id=user_id, read=False
        ).order_by(Notification.created_at.desc()).all()

    def get_user_notifications(self, user_id: int, limit: int = None) -> List[Notification]:
        """Get all notifications for user."""
        q = Notification.query.filter_by(user_id=user_id) \
            .order_by(Notification.created_at.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def mark_read(self, notification: Notification) -> None:
        notification.read = True

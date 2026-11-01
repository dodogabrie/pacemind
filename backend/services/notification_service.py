"""Notification service - generates and manages user notifications."""

import logging
from datetime import datetime
from models.notification import Notification
from models.training_plan import TrainingPlan
from repositories import NotificationRepository, TrainingPlanRepository

logger = logging.getLogger(__name__)


class NotificationService:
    """Generates notifications based on compliance and race events."""

    def __init__(self, notification_repo=None, training_plan_repo=None):
        self.notification_repo = notification_repo or NotificationRepository()
        self.training_plan_repo = training_plan_repo or TrainingPlanRepository()

    def generate_weekly_summary(self, user_id: int, plan_id: int, compliance_pct: float):
        """Generate a weekly compliance summary notification."""
        plan = self.training_plan_repo.get_by_id(plan_id)
        if not plan:
            return

        if compliance_pct >= 80:
            title = "Great training week!"
            message = f"You hit {compliance_pct:.0f}% compliance this week. Keep it up!"
        elif compliance_pct >= 60:
            title = "Decent training week"
            message = f"You reached {compliance_pct:.0f}% compliance. A bit more consistency would help."
        else:
            title = "Training below target"
            message = (
                f"Only {compliance_pct:.0f}% compliance this week. "
                "Consider asking your coach for plan adjustments."
            )

        self._create(user_id, 'weekly_summary', title, message, plan_id)

    def generate_coach_suggestion(self, user_id: int, plan_id: int):
        """Generate a coach suggestion notification when compliance is low."""
        self._create(
            user_id, 'coach_suggestion',
            "Your coach has a suggestion",
            "Your recent training has been below target. Open the Race Dashboard to chat with your coach about adjustments.",
            plan_id,
        )

    def generate_race_countdown(self, user_id: int, plan_id: int, days_to_race: int):
        """Generate race countdown notifications at key milestones."""
        messages = {
            7: ("1 week to race day!", "Final week! Time to taper and rest. Trust your training."),
            3: ("3 days to go!", "Almost there. Focus on sleep, nutrition, and light movement."),
            1: ("Race day tomorrow!", "Rest up tonight. Lay out your gear. You're ready."),
        }

        if days_to_race not in messages:
            return

        title, message = messages[days_to_race]

        # Don't duplicate
        existing = self.notification_repo.find_one_by(
            user_id=user_id, plan_id=plan_id, type='race_countdown', title=title
        )
        if existing:
            return

        self._create(user_id, 'race_countdown', title, message, plan_id)

    def get_unread_count(self, user_id: int) -> int:
        """Get count of unread notifications."""
        return len(self.notification_repo.get_unread(user_id))

    def get_notifications(self, user_id: int, limit: int = 20) -> list:
        """Get recent notifications for a user."""
        notifs = self.notification_repo.get_user_notifications(user_id, limit=limit)
        return [n.to_dict() for n in notifs]

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        """Mark a notification as read."""
        notif = self.notification_repo.find_one_by(id=notification_id, user_id=user_id)
        if not notif:
            return False
        self.notification_repo.mark_read(notif)
        self.notification_repo.commit()
        return True

    def mark_all_read(self, user_id: int) -> int:
        """Mark all notifications as read. Returns count updated."""
        unread = self.notification_repo.get_unread(user_id)
        for notif in unread:
            self.notification_repo.mark_read(notif)
        self.notification_repo.commit()
        return len(unread)

    def _create(self, user_id: int, ntype: str, title: str, message: str, plan_id: int = None):
        """Create a notification."""
        notif = Notification(
            user_id=user_id,
            type=ntype,
            title=title,
            message=message,
            plan_id=plan_id,
        )
        self.notification_repo.create(notif)
        self.notification_repo.commit()
        logger.info(f"Notification created: user={user_id} type={ntype} title={title}")

"""DailyCheckin repository."""

from datetime import date, timedelta
from typing import List, Optional

from models import DailyCheckin
from repositories.base import BaseRepository


class DailyCheckinRepository(BaseRepository[DailyCheckin]):
    model = DailyCheckin

    def get_for_date(self, user_id: int, day: date) -> Optional[DailyCheckin]:
        return self.find_one_by(user_id=user_id, date=day)

    def get_recent(self, user_id: int, days: int = 7) -> List[DailyCheckin]:
        """Most-recent first; up to ``days`` calendar days back."""
        cutoff = date.today() - timedelta(days=days)
        return (
            DailyCheckin.query
            .filter(DailyCheckin.user_id == user_id, DailyCheckin.date >= cutoff)
            .order_by(DailyCheckin.date.desc())
            .all()
        )

    def upsert(self, user_id: int, day: date, fields: dict) -> DailyCheckin:
        """Insert or update the row for (user_id, date)."""
        existing = self.get_for_date(user_id, day)
        if existing is None:
            existing = DailyCheckin(user_id=user_id, date=day)
            self.create(existing)
        for k, v in fields.items():
            setattr(existing, k, v)
        return existing

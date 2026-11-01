"""Activity repository (any source: strava, garmin, uploads)."""

from typing import Optional, List
from datetime import datetime
from models import Activity
from database import db
from repositories.base import BaseRepository


class ActivityRepository(BaseRepository[Activity]):
    model = Activity

    def get_user_activities(self, user_id: int, after: datetime = None,
                            limit: int = None) -> List[Activity]:
        """Get activities for user, optionally filtered by date."""
        q = Activity.query.filter_by(user_id=user_id)
        if after:
            q = q.filter(Activity.start_date >= after)
        q = q.order_by(Activity.start_date.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def get_activities_with_streams(self, user_id: int, after: datetime = None,
                                     limit: int = None) -> List[Activity]:
        """Get activities that have stream data, avoiding loading large TEXT columns initially."""
        q = db.session.query(Activity.id) \
            .filter_by(user_id=user_id) \
            .filter(Activity._streams.isnot(None))
        if after:
            q = q.filter(Activity.start_date >= after)
        q = q.order_by(Activity.start_date.desc())
        if limit:
            q = q.limit(limit)
        activity_ids = [row[0] for row in q.all()]
        if not activity_ids:
            return []
        return Activity.query.filter(Activity.id.in_(activity_ids)).all()

    def get_by_strava_id(self, user_id: int, strava_id: int) -> Optional[Activity]:
        """Get activity by user and Strava API ID."""
        return self.find_one_by(user_id=user_id, strava_id=strava_id)

    def get_by_external_id(self, user_id: int, source: str,
                           external_id: str) -> Optional[Activity]:
        """Get activity by the provider's own id for that source."""
        return self.find_one_by(user_id=user_id, source=source,
                                external_id=str(external_id))

    def get_by_dedup_key(self, user_id: int, dedup_key: str) -> Optional[Activity]:
        """Get the existing row for the same session, whatever its source."""
        return self.find_one_by(user_id=user_id, dedup_key=dedup_key)

    def get_by_dedup_keys(self, user_id: int, keys: List[str]) -> List[Activity]:
        """Rows whose dedup_key is any of `keys` — the neighbour-bucket probe."""
        if not keys:
            return []
        return Activity.query.filter(
            Activity.user_id == user_id,
            Activity.dedup_key.in_(keys)
        ).all()

    def get_downloaded_ids(self, user_id: int, strava_ids: list) -> List[Activity]:
        """Get activities matching a list of Strava IDs."""
        return Activity.query.filter(
            Activity.user_id == user_id,
            Activity.strava_id.in_(strava_ids)
        ).all()

    def count_for_user(self, user_id: int) -> int:
        return self.count(user_id=user_id)

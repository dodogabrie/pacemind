"""Performance snapshot and grade performance repository."""

from typing import Optional, List
from models import PerformanceSnapshot, GradePerformanceHistory
from database import db
from repositories.base import BaseRepository


class PerformanceRepository(BaseRepository[PerformanceSnapshot]):
    model = PerformanceSnapshot

    def get_user_snapshots(self, user_id: int, limit: int = None) -> List[PerformanceSnapshot]:
        """Get snapshots for user, newest first."""
        q = PerformanceSnapshot.query.filter_by(user_id=user_id) \
            .order_by(PerformanceSnapshot.period_start.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def get_snapshots_by_period(self, user_id: int, period_type: str,
                                 limit: int = None) -> List[PerformanceSnapshot]:
        """Get snapshots filtered by period type."""
        q = PerformanceSnapshot.query.filter_by(
            user_id=user_id, period_type=period_type
        ).order_by(PerformanceSnapshot.period_start.desc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def get_by_period_name(self, user_id: int, period_name: str) -> Optional[PerformanceSnapshot]:
        """Get snapshot by period name (e.g. '2025-W03')."""
        return self.find_one_by(user_id=user_id, period_name=period_name)

    def create_with_grades(self, snapshot: PerformanceSnapshot,
                            grade_data: list) -> PerformanceSnapshot:
        """Create snapshot with associated grade performance records."""
        self.create(snapshot)
        for data in grade_data:
            grade_perf = GradePerformanceHistory(
                snapshot_id=snapshot.id,
                user_id=snapshot.user_id,
                **data
            )
            db.session.add(grade_perf)
        db.session.flush()
        return snapshot

    def get_grade_performances(self, user_id: int) -> List[GradePerformanceHistory]:
        """Get all grade performance records for user."""
        return GradePerformanceHistory.query.filter_by(user_id=user_id).all()

    def get_grade_trends(self, user_id: int, periods: int = 10) -> List[GradePerformanceHistory]:
        """Get grade performance with snapshot join, limited to recent periods."""
        return GradePerformanceHistory.query \
            .join(PerformanceSnapshot) \
            .filter(PerformanceSnapshot.user_id == user_id) \
            .order_by(PerformanceSnapshot.period_start.desc()) \
            .limit(periods).all()

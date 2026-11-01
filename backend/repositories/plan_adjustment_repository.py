"""PlanAdjustment repository - structured audit trail queries."""

from datetime import date, datetime, time, timezone
from typing import List, Optional

from models import PlanAdjustment
from repositories.base import BaseRepository


class PlanAdjustmentRepository(BaseRepository[PlanAdjustment]):
    model = PlanAdjustment

    def list_for_plan(self, plan_id: int, user_id: int,
                      since: Optional[date] = None) -> List[PlanAdjustment]:
        """Adjustments for a plan, most-recent first.

        Scoped by ``user_id`` so a caller can only read their own plan's trail.
        ``since`` (a calendar date) filters to adjustments applied on or after
        that day.
        """
        query = PlanAdjustment.query.filter(
            PlanAdjustment.plan_id == plan_id,
            PlanAdjustment.user_id == user_id,
        )
        if since is not None:
            cutoff = datetime.combine(since, time.min, tzinfo=timezone.utc)
            query = query.filter(PlanAdjustment.applied_at >= cutoff)
        return query.order_by(PlanAdjustment.applied_at.desc()).all()

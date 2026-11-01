"""PlanAdjustment model - structured audit trail for automatic plan mutations.

Every time ``services.plan_adjustment_service.PlanAdjustmentService`` mutates a
plan's ``weeks`` JSON (a readiness-driven *swap* or *downgrade*), it writes one
row here. Previously the only record of a mutation was the free-text
``notifications.message`` string, which is lossy: it can't answer "show me every
adjustment that touched plan X in the last 30 days" with a structured query,
can't drive an audit pane in the UI, and can't be replayed.

Each row is joinable to the ``TrainingPlan`` it changed and (when the trigger
was a real morning check-in) to the ``DailyCheckin`` that caused it.
``payload_json`` carries the full before/after of the affected day(s) so a
single adjustment can be inspected or reverted.

GH issue: coach-review #68.

Citations:
  - Halson, S. L. (2014). Monitoring training load to understand fatigue in
    athletes. Sports Med — training records (incl. modification history) are
    part of the load model.
  - Coggan, A. R. — Performance Manager Chart: every "actual != planned" event
    should be a typed datum, not a free-text comment.
"""

from database import db
from datetime import datetime, timezone


VALID_KINDS = ('swap', 'downgrade')
VALID_TRIGGERS = ('daily_checkin', 'compliance', 'tsb', 'manual')


class PlanAdjustment(db.Model):
    """One applied, readiness-driven mutation of a training plan."""

    __tablename__ = 'plan_adjustments'
    __table_args__ = (
        db.Index('ix_plan_adjustment_plan_applied', 'plan_id', 'applied_at'),
        db.Index('ix_plan_adjustment_user_applied', 'user_id', 'applied_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plans.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    applied_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    # One of VALID_KINDS.
    kind = db.Column(db.String(16), nullable=False)
    # One of VALID_TRIGGERS. 'daily_checkin' = real morning check-in,
    # 'tsb' = synthetic (passive readiness) signal.
    trigger = db.Column(db.String(16), nullable=False)

    # swap: workout moved from day_before's slot to day_after's slot.
    # downgrade: day_before == day_after (the single day that was softened).
    day_before = db.Column(db.String(16), nullable=True)
    day_after = db.Column(db.String(16), nullable=True)

    workout_type_before = db.Column(db.String(32), nullable=True)
    workout_type_after = db.Column(db.String(32), nullable=True)

    # The check-in that triggered this, when it was a real one (NULL for
    # synthetic/TSB-driven adjustments — those have no DailyCheckin row).
    checkin_id = db.Column(db.Integer, db.ForeignKey('daily_checkins.id'),
                           nullable=True)

    # Full before/after of the affected day(s) for inspection / replay.
    payload_json = db.Column(db.JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'plan_id': self.plan_id,
            'applied_at': self.applied_at.isoformat() if self.applied_at else None,
            'kind': self.kind,
            'trigger': self.trigger,
            'day_before': self.day_before,
            'day_after': self.day_after,
            'workout_type_before': self.workout_type_before,
            'workout_type_after': self.workout_type_after,
            'checkin_id': self.checkin_id,
            'payload': self.payload_json,
        }

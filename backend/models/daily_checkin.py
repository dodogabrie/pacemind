"""DailyCheckin model - morning subjective readiness probe.

Captures the runner's subjective state (RPE of the previous session, overall
feeling, sleep, soreness) for the calendar day. Drives the readiness-aware
plan adjustments in ``services.plan_adjustment_service``: a bad checkin can
swap today's quality session with the easiest remaining day of the same week.

Citations:
  - Foster, C. (1998). Monitoring training in athletes with reference to
    overtraining syndrome. Med Sci Sports Exerc — sRPE foundational paper.
  - Saw, A. E. et al. (2016). Monitoring the athlete training response.
    Br J Sports Med — subjective measures outperform objective ones for
    fatigue.

GH issue: coach-review #55.
"""

from database import db
from datetime import datetime, timezone


VALID_FEELINGS = ('great', 'good', 'ok', 'tired', 'bad')


class DailyCheckin(db.Model):
    """Morning subjective check-in for the day."""

    __tablename__ = 'daily_checkins'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uq_daily_checkin_user_date'),
        db.Index('ix_daily_checkin_user_date', 'user_id', 'date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)

    # RPE 1..10 reported for *yesterday*'s session (None if no session done).
    rpe_yesterday = db.Column(db.Integer, nullable=True)
    # One of VALID_FEELINGS; "ok" is the neutral default.
    feeling = db.Column(db.String(16), nullable=True)
    # Hours of sleep last night.
    sleep_h = db.Column(db.Float, nullable=True)
    # Soreness 0..10 (0 = none, 10 = can't walk).
    soreness = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'rpe_yesterday': self.rpe_yesterday,
            'feeling': self.feeling,
            'sleep_h': self.sleep_h,
            'soreness': self.soreness,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @property
    def is_bad_day(self) -> bool:
        """Heuristic: today's training should be downshifted.

        Combines the three signals the coaching literature flags as
        non-adaptive: high prior-session RPE, subjective fatigue, and short
        sleep. Any one strongly-positive signal trips it.
        """
        if self.feeling == 'bad':
            return True
        if self.rpe_yesterday is not None and self.rpe_yesterday >= 8:
            return True
        if self.soreness is not None and self.soreness >= 7:
            return True
        if self.sleep_h is not None and self.sleep_h < 5:
            return True
        return False

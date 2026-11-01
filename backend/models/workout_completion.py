"""Workout completion model - tracks activity-to-plan matching and compliance."""

from database import db
from datetime import datetime, timezone


class WorkoutCompletion(db.Model):
    """Tracks whether a planned workout was completed, and how well."""
    __tablename__ = 'workout_completions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plans.id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    day = db.Column(db.String(16), nullable=False)  # "Monday", "Tuesday", etc.

    strava_activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=True)

    # Planned vs actual
    planned_distance_km = db.Column(db.Float, nullable=True)
    actual_distance_km = db.Column(db.Float, nullable=True)
    planned_workout_type = db.Column(db.String(32), nullable=True)
    planned_elevation_m = db.Column(db.Float, nullable=True)
    actual_elevation_m = db.Column(db.Float, nullable=True)

    compliance_score = db.Column(db.Integer, nullable=True)  # 0-100
    status = db.Column(db.String(16), nullable=False)  # completed, partial, missed, upcoming

    matched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Unique constraint: one completion per plan/week/day
    __table_args__ = (
        db.UniqueConstraint('plan_id', 'week_number', 'day', name='uq_plan_week_day'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'plan_id': self.plan_id,
            'week_number': self.week_number,
            'day': self.day,
            'strava_activity_id': self.strava_activity_id,
            'planned_distance_km': self.planned_distance_km,
            'actual_distance_km': self.actual_distance_km,
            'planned_workout_type': self.planned_workout_type,
            'planned_elevation_m': self.planned_elevation_m,
            'actual_elevation_m': self.actual_elevation_m,
            'compliance_score': self.compliance_score,
            'status': self.status,
            'matched_at': self.matched_at.isoformat() if self.matched_at else None,
        }

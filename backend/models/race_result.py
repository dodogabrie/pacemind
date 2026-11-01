"""Race result model for post-race analysis."""

from database import db
from datetime import datetime, timezone


class RaceResult(db.Model):
    """Stores post-race analysis comparing actual vs predicted performance."""

    # TODO(coach-review #10 — see GH issues): result is stored but never feeds back.
    # Insertion of a RaceResult should trigger recalibration_service: damped-Bayesian
    # update of UserLearnedParams.v_flat (α ≈ 0.3-0.5), then plan_adjustment_service
    # .reevaluate_plan for the active A-race plan. Persist the diff in
    # TrainingPlan.recalibration_history for audit.
    __tablename__ = 'race_results'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plans.id'), unique=True, nullable=False)
    strava_activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)
    prediction_id = db.Column(db.Integer, db.ForeignKey('predictions.id'), nullable=True)

    actual_total_seconds = db.Column(db.Float, nullable=False)
    predicted_total_seconds = db.Column(db.Float, nullable=True)
    difference_seconds = db.Column(db.Float, nullable=True)

    # [{km, predicted_pace, actual_pace, diff_seconds, grade, elevation_gain, insight}, ...]
    split_comparison = db.Column(db.JSON, nullable=True)
    # ["Lost 3:20 on km 18-22 (steep climb)...", ...]
    insights = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'plan_id': self.plan_id,
            'strava_activity_id': self.strava_activity_id,
            'prediction_id': self.prediction_id,
            'actual_total_seconds': self.actual_total_seconds,
            'predicted_total_seconds': self.predicted_total_seconds,
            'difference_seconds': self.difference_seconds,
            'split_comparison': self.split_comparison or [],
            'insights': self.insights or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

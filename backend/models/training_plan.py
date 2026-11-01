"""Training plan model for personalized multi-week training plans."""

from database import db
from datetime import datetime, timezone


class TrainingPlan(db.Model):
    """Stores agent-generated training plans."""
    __tablename__ = 'training_plans'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    target_gpx_id = db.Column(db.Integer, db.ForeignKey('gpx_files.id'), nullable=True)
    race_id = db.Column(db.Integer, db.ForeignKey('races.id'), nullable=True, index=True)

    plan_name = db.Column(db.String(255), nullable=False)
    race_date = db.Column(db.DateTime, nullable=True)
    race_description = db.Column(db.Text, nullable=True)

    # List of week objects with days, workouts, etc.
    weeks = db.Column(db.JSON, nullable=False, default=list)

    # List of {date, predicted_seconds} tracking prediction trend over time
    prediction_history = db.Column(db.JSON, nullable=True, default=list)

    # Feasibility warnings emitted by validate_plan_feasibility().
    # [{severity, week, day, issue, target, cap, suggestion}]
    warnings = db.Column(db.JSON, nullable=True, default=list)

    race_priority = db.Column(db.String(1), nullable=True)  # 'A', 'B', 'C'

    status = db.Column(db.String(32), nullable=False, default='draft')
    # 'draft', 'active', 'completed'

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'target_gpx_id': self.target_gpx_id,
            'race_id': self.race_id,
            'plan_name': self.plan_name,
            'race_date': self.race_date.isoformat() if self.race_date else None,
            'race_description': self.race_description,
            'race_priority': self.race_priority,
            'weeks': self.weeks or [],
            'prediction_history': self.prediction_history or [],
            'warnings': self.warnings or [],
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_summary(self):
        return {
            'id': self.id,
            'plan_name': self.plan_name,
            'race_id': self.race_id,
            'race_date': self.race_date.isoformat() if self.race_date else None,
            'race_priority': self.race_priority,
            'status': self.status,
            'weeks_count': len(self.weeks) if self.weeks else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

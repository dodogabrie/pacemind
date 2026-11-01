"""User residual model for Tier 3 ML predictions."""

from datetime import datetime, timezone
from database import db


class UserResidualModel(db.Model):
    """Tier 3: the user's personal-habits model and its activation gate.

    `model_blob` is a joblib bundle from services/residual_ml_service.fit()
    (ridge on per-200 m course features, target log(actual / Tier 2 physics)).
    `metrics` holds the gate: {'open', 'reason', 'n_eval', 'mape_t2', 'mape_t3',
    'bias_t2', 'bias_t3', 't3_log_errors', ...}; the model is used only when
    metrics['open'] is true. `feature_importance` holds the readable habits
    (% slower(+)/faster(-) than Tier 2).

    Privacy: trained only on the individual user's own activities.
    """

    __tablename__ = 'user_residual_models'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    model_blob = db.Column(db.LargeBinary, nullable=False)
    n_activities_used = db.Column(db.Integer, nullable=False)
    n_segments_trained = db.Column(db.Integer)
    metrics = db.Column(db.JSON)
    feature_importance = db.Column(db.JSON)
    model_config = db.Column(db.JSON)
    residual_variance = db.Column(db.Float)  # unused since the rebuild; kept to avoid a migration

    last_trained = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    version = db.Column(db.Integer, default=1)

    user = db.relationship('User', backref=db.backref('residual_model', uselist=False))

    def __repr__(self):
        return f'<UserResidualModel user_id={self.user_id} gate={(self.metrics or {}).get("open")}>'

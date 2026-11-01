from database import db
from datetime import datetime, timezone
from models._crypto import cipher


class User(db.Model):
    """User model for multi-user support."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    # Nullable since email accounts exist without Strava. Kept (rather than
    # moved to user_connections) because ~9 read sites still use it; dropping
    # it is a later cleanup.
    strava_user_id = db.Column(db.Integer, unique=True, nullable=True)
    strava_username = db.Column(db.String(255))

    # Identity / login
    password_hash = db.Column(db.String(255), nullable=True)   # null for OAuth + magic-link accounts
    auth_provider = db.Column(db.String(32), nullable=True, default='strava')  # strava|email
    email_verified_at = db.Column(db.DateTime, nullable=True)

    # Encrypted tokens
    _access_token = db.Column('access_token', db.LargeBinary, nullable=True)
    _refresh_token = db.Column('refresh_token', db.LargeBinary, nullable=True)
    expires_at = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # User fingerprint for personalized predictions
    user_endurance_score = db.Column(db.Float, nullable=True)
    user_recovery_rate = db.Column(db.Float, nullable=True)
    user_base_fitness = db.Column(db.Float, nullable=True)
    fingerprint_calibrated_at = db.Column(db.DateTime, nullable=True)
    fingerprint_activity_count = db.Column(db.Integer, nullable=True)

    # User calibration profile (editable pace curve)
    saved_flat_pace = db.Column(db.Float, nullable=True)
    saved_anchor_ratios = db.Column(db.JSON, nullable=True)
    calibration_updated_at = db.Column(db.DateTime, nullable=True)
    calibration_activity_id = db.Column(db.Integer, nullable=True)

    # Physics model parameters
    physics_params = db.Column(db.JSON, nullable=True)

    # Training base location
    training_base_lat = db.Column(db.Float, nullable=True)
    training_base_lon = db.Column(db.Float, nullable=True)
    training_base_name = db.Column(db.String(255), nullable=True)
    training_travel_radius_km = db.Column(db.Float, nullable=True, default=30)

    # Relationships
    gpx_files = db.relationship('GPXFile', backref='user', lazy=True, cascade='all, delete-orphan')
    strava_activities = db.relationship('Activity', backref='user', lazy=True, cascade='all, delete-orphan')
    connections = db.relationship('UserConnection', backref='user', lazy=True, cascade='all, delete-orphan')

    @property
    def access_token(self):
        """Decrypt access token."""
        if self._access_token:
            return cipher.decrypt(self._access_token).decode()
        return None

    @access_token.setter
    def access_token(self, value):
        """Encrypt access token."""
        if value:
            self._access_token = cipher.encrypt(value.encode())
        else:
            self._access_token = None

    @property
    def refresh_token(self):
        """Decrypt refresh token."""
        if self._refresh_token:
            return cipher.decrypt(self._refresh_token).decode()
        return None

    @refresh_token.setter
    def refresh_token(self, value):
        """Encrypt refresh token."""
        if value:
            self._refresh_token = cipher.encrypt(value.encode())
        else:
            self._refresh_token = None

    def to_dict(self):
        """Convert user to dictionary."""
        return {
            'id': self.id,
            'strava_user_id': self.strava_user_id,
            'strava_username': self.strava_username,
            'email': self.email,
            'auth_provider': self.auth_provider,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat(),
            'fingerprint': {
                'endurance_score': self.user_endurance_score,
                'recovery_rate': self.user_recovery_rate,
                'base_fitness': self.user_base_fitness,
                'calibrated_at': self.fingerprint_calibrated_at.isoformat() if self.fingerprint_calibrated_at else None,
                'activity_count': self.fingerprint_activity_count
            } if self.user_endurance_score is not None else None,
            'calibration': {
                'flat_pace': self.saved_flat_pace,
                'anchor_ratios': self.saved_anchor_ratios,
                'updated_at': self.calibration_updated_at.isoformat() if self.calibration_updated_at else None,
                'activity_id': self.calibration_activity_id
            } if self.saved_flat_pace is not None else None
        }

    def get_fingerprint_array(self):
        """Get fingerprint as array for ML model.

        Returns:
            List of [endurance_score, recovery_rate, base_fitness] or None if not calibrated
        """
        if self.user_endurance_score is None:
            return None
        return [
            float(self.user_endurance_score),
            float(self.user_recovery_rate),
            float(self.user_base_fitness)
        ]

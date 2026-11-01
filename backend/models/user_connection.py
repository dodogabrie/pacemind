"""External provider connection (Strava, Garmin, …) attached to a user.

One row per (user, provider). Adding a new data source is an insert, not a
schema change. Tokens are encrypted at rest with the shared Fernet cipher.
"""

from database import db
from datetime import datetime, timezone
from models._crypto import cipher


class UserConnection(db.Model):
    __tablename__ = 'user_connections'
    __table_args__ = (
        db.UniqueConstraint('provider', 'external_user_id',
                            name='uq_connection_provider_external'),
        db.UniqueConstraint('user_id', 'provider',
                            name='uq_connection_user_provider'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider = db.Column(db.String(32), nullable=False)  # strava|garmin|polar|coros|suunto
    external_user_id = db.Column(db.String(128), nullable=False)

    # Encrypted tokens
    _access_token = db.Column('access_token', db.LargeBinary, nullable=True)
    _refresh_token = db.Column('refresh_token', db.LargeBinary, nullable=True)
    expires_at = db.Column(db.Integer, nullable=True)

    scopes = db.Column(db.String(512), nullable=True)
    connected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_sync_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(32), default='active')  # active|revoked|error

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
        """Convert connection to dictionary (never exposes tokens)."""
        return {
            'id': self.id,
            'provider': self.provider,
            'external_user_id': self.external_user_id,
            'scopes': self.scopes,
            'status': self.status,
            'connected_at': self.connected_at.isoformat() if self.connected_at else None,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
        }

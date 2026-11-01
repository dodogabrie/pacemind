"""A place the user trains from, owning some weekdays (0=Monday..6=Sunday)."""

from database import db
from datetime import datetime, timezone


class TrainingLocation(db.Model):
    __tablename__ = 'training_locations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    radius_km = db.Column(db.Float, nullable=False, default=10)
    weekdays = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'lat': self.lat, 'lon': self.lon,
            'radius_km': self.radius_km, 'weekdays': self.weekdays or [],
        }

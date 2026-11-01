"""Weather cache model for weather API responses."""

from database import db
from datetime import datetime, timezone


class WeatherCache(db.Model):
    """Cache table for weather API responses."""
    __tablename__ = 'weather_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False)
    cache_type = db.Column(db.String(16), nullable=False)  # 'historical' or 'forecast'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)

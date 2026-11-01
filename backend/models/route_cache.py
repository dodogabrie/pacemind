"""Route cache model for ORS routing query results."""

from database import db
from datetime import datetime, timezone


class RouteCache(db.Model):
    """Cache table for OpenRouteService routing responses keyed by waypoint hash."""
    __tablename__ = 'route_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False)
    hits = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)

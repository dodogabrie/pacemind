"""Terrain cache model for OSM terrain query results."""

from database import db
from datetime import datetime, timezone


class TerrainCache(db.Model):
    """Cache table for OSM terrain query results."""
    __tablename__ = 'terrain_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)

"""Training route model for reusable routes linked to workouts."""

from database import db
from datetime import datetime, timezone


class TrainingRoute(db.Model):
    """Stores training routes (imported from Strava or generated via ORS)."""
    __tablename__ = 'training_routes'
    __table_args__ = (
        db.Index('ix_training_route_user', 'user_id'),
        db.Index('ix_training_route_center', 'center_lat', 'center_lon'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(32), nullable=False, default='imported')
    # 'imported' (from Strava), 'generated' (ORS), 'strava'

    # Route geometry — same point format as GPXFile for pipeline compatibility
    # [{lat, lon, elevation, distance}, ...]
    route_data = db.Column(db.JSON, nullable=False)

    # Pre-computed stats
    distance_km = db.Column(db.Float, nullable=False, default=0)
    elevation_gain_m = db.Column(db.Float, nullable=False, default=0)
    elevation_loss_m = db.Column(db.Float, nullable=False, default=0)

    # Center point for location-based search
    center_lat = db.Column(db.Float, nullable=True)
    center_lon = db.Column(db.Float, nullable=True)

    # Pre-computed segments from segmentation_service
    segments = db.Column(db.JSON, nullable=True)

    # Cached terrain summary from osm_terrain_service
    terrain_summary = db.Column(db.JSON, nullable=True)

    # User-defined tags e.g. ['hilly', 'technical', 'flat']
    tags = db.Column(db.JSON, nullable=True, default=list)

    # ORS generation params for re-generation
    generation_params = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'source': self.source,
            'route_data': self.route_data,
            'distance_km': self.distance_km,
            'elevation_gain_m': self.elevation_gain_m,
            'elevation_loss_m': self.elevation_loss_m,
            'center_lat': self.center_lat,
            'center_lon': self.center_lon,
            'segments': self.segments,
            'terrain_summary': self.terrain_summary,
            'tags': self.tags or [],
            'generation_params': self.generation_params,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_summary(self):
        return {
            'id': self.id,
            'name': self.name,
            'source': self.source,
            'distance_km': self.distance_km,
            'elevation_gain_m': self.elevation_gain_m,
            'elevation_loss_m': self.elevation_loss_m,
            'tags': self.tags or [],
            'terrain_summary': self.terrain_summary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'route_data': self._thumbnail_points(),
        }

    def _thumbnail_points(self, max_points=60):
        """Downsample route_data for card thumbnails (lat/lon only)."""
        rd = self.route_data
        if not rd:
            return []
        step = max(1, len(rd) // max_points)
        return [{'lat': p['lat'], 'lon': p['lon']} for p in rd[::step]]

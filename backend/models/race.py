"""Race model for the public race calendar.

Stores curated + provider-imported race events. Decoupled from
``RaceResult`` (post-race actuals) and from ``TrainingPlan`` (a plan may
be linked to a race via ``training_plans.race_id`` once a user picks one
as A/B/C, but a race can exist without any plan).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import column_property, deferred

from database import db


class Race(db.Model):
    """A race event in the public calendar."""
    __tablename__ = 'races'

    id = db.Column(db.Integer, primary_key=True)

    # Provenance
    source = db.Column(db.String(16), nullable=False, default='seed')  # seed|itra|fidal|user
    external_id = db.Column(db.String(128), nullable=True)  # provider id, nullable for source='user'

    # Identity
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False, unique=True)
    url = db.Column(db.String(512), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # When + where
    date = db.Column(db.Date, nullable=False, index=True)
    country = db.Column(db.String(2), nullable=True, index=True)  # ISO-2
    region = db.Column(db.String(128), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)

    # Course profile
    distance_km = db.Column(db.Float, nullable=False)
    elev_gain_m = db.Column(db.Float, nullable=True)
    elev_loss_m = db.Column(db.Float, nullable=True)
    surface = db.Column(db.String(16), nullable=True)  # asphalt|trail|mixed
    race_type = db.Column(db.String(16), nullable=True)  # road|trail|ultra|vertical
    itra_points = db.Column(db.Integer, nullable=True)

    # Web discovery (source='web'): next-edition date may be inferred from past
    # editions; poster + GPX live in the row (no persistent disk in the container).
    date_estimated = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    poster_data = deferred(db.Column(db.LargeBinary, nullable=True))
    poster_mime = db.Column(db.String(32), nullable=True)
    gpx_data = deferred(db.Column(db.Text, nullable=True))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint('source', 'external_id', name='uq_race_source_external'),
        db.Index('ix_race_date_country', 'date', 'country'),
        db.Index('ix_race_distance', 'distance_km'),
    )

    def to_summary(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'date': self.date.isoformat() if self.date else None,
            'country': self.country,
            'location': self.location,
            'lat': self.lat,
            'lon': self.lon,
            'distance_km': self.distance_km,
            'elev_gain_m': self.elev_gain_m,
            'race_type': self.race_type,
            'surface': self.surface,
            'date_estimated': bool(self.date_estimated),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'external_id': self.external_id,
            'name': self.name,
            'slug': self.slug,
            'url': self.url,
            'description': self.description,
            'date': self.date.isoformat() if self.date else None,
            'country': self.country,
            'region': self.region,
            'location': self.location,
            'lat': self.lat,
            'lon': self.lon,
            'distance_km': self.distance_km,
            'elev_gain_m': self.elev_gain_m,
            'elev_loss_m': self.elev_loss_m,
            'surface': self.surface,
            'race_type': self.race_type,
            'itra_points': self.itra_points,
            'date_estimated': bool(self.date_estimated),
            'has_poster': self.poster_mime is not None,
            'has_gpx': bool(self.has_gpx),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# Cheap "is there a track" flag without loading the deferred GPX text.
Race.has_gpx = column_property(Race.__table__.c.gpx_data.isnot(None))

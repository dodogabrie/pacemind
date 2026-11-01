"""User training preferences — persistent profile for plan generation."""

from datetime import datetime, timezone
from database import db


class UserTrainingPreferences(db.Model):
    """Persistent training preferences for a user.

    One row per user. These preferences are loaded by the agent before
    generating a training plan, so the user doesn't have to repeat them
    every conversation.
    """

    # TODO(coach-review #57 — see GH issues): no anthropometrics (weight / body comp).
    # Blocks RED-S screening, hydration sanity checks, and W/kg metrics. Add a
    # separate BodyMeasurement table (date-series) rather than denormalising here.

    __tablename__ = 'user_training_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)

    # Schedule preferences
    long_run_day = db.Column(db.String(16), nullable=True)       # "Saturday" / "Sunday"
    back_to_back = db.Column(db.Boolean, default=False)          # hard session day before long run
    rest_days = db.Column(db.JSON, default=list)                 # ["Friday"]

    # Mountain / elevation access — calendar mask of candidate days
    mountain_days = db.Column(db.JSON, default=list)             # ["Saturday", "Sunday"]

    # Mountain access — frequency budget (engine prefers per_week, falls back to per_month/4.33)
    mountain_access_per_week = db.Column(db.Float, nullable=True)     # e.g. 1.0, 0.5
    mountain_access_per_month = db.Column(db.Integer, nullable=True)  # e.g. 2
    max_mountain_elevation_m = db.Column(db.Integer, nullable=True)   # cap per outing
    max_mountain_distance_km = db.Column(db.Float, nullable=True)
    sample_mountain_route_id = db.Column(
        db.Integer,
        db.ForeignKey('training_routes.id', ondelete='SET NULL'),
        nullable=True,
    )

    # Volume capacity caps
    max_weekly_km = db.Column(db.Float, nullable=True)
    max_long_run_km = db.Column(db.Float, nullable=True)
    max_long_run_hours = db.Column(db.Float, nullable=True)

    # Time-budget caps (primary driver in time-first onboarding).
    # km caps above stay as a secondary safety net.
    available_hours_per_week = db.Column(db.Float, nullable=True)
    usual_midweek_hours = db.Column(db.Float, nullable=True)
    max_mountain_hours_per_outing = db.Column(db.Float, nullable=True)

    # Terrain context (inferred or user-confirmed)
    terrain_profile = db.Column(db.String(32), nullable=True)
    # 'flat_urban' | 'rolling_hills' | 'mountain'
    terrain_profile_source = db.Column(db.String(16), default='inferred')
    # 'inferred' | 'user'

    # Time constraints
    max_hours_per_day = db.Column(db.Float, nullable=True)       # e.g. 2.0

    # Strength training
    strength_training_days = db.Column(db.Integer, default=0)    # 0-3
    strength_preferred_days = db.Column(db.JSON, default=list)   # ["Tuesday", "Thursday"]

    # Pace-zone derivation method (#61). 'physics' = multipliers on the
    # physics-extracted v_flat (default); 'vdot' = Daniels' VDOT from a recent
    # race; 'riegel' = Riegel projection from a recent race. The vdot/riegel
    # modes need a reference race result stored below.
    pace_zone_method = db.Column(db.String(16), default='physics')
    pace_zone_race_distance_m = db.Column(db.Float, nullable=True)
    pace_zone_race_time_s = db.Column(db.Float, nullable=True)

    # Heart-rate anchors (#59). Optional; enable Karvonen / %HRmax / LTHR-based
    # HR zones surfaced alongside pace targets. Auto-detectable from Strava
    # (max observed HR × 1.02). bpm integers.
    hr_max = db.Column(db.Integer, nullable=True)
    hr_rest = db.Column(db.Integer, nullable=True)
    lthr = db.Column(db.Integer, nullable=True)

    # Running-power FTP (#60). Optional; enables Coggan-style power zones for
    # Stryd / Garmin Running Power users. Auto-detectable from Strava streams
    # (best 20-min avg watts × 0.95). Watts integer.
    ftp_w = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('training_preferences', uselist=False))

    VALID_DAYS = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'}
    VALID_TERRAIN_PROFILES = {'flat_urban', 'rolling_hills', 'mountain'}
    VALID_PACE_ZONE_METHODS = {'physics', 'vdot', 'riegel'}

    def to_dict(self):
        return {
            'long_run_day': self.long_run_day,
            'back_to_back': self.back_to_back,
            'rest_days': self.rest_days or [],
            'mountain_days': self.mountain_days or [],
            'mountain_access_per_week': self.mountain_access_per_week,
            'mountain_access_per_month': self.mountain_access_per_month,
            'max_mountain_elevation_m': self.max_mountain_elevation_m,
            'max_mountain_distance_km': self.max_mountain_distance_km,
            'sample_mountain_route_id': self.sample_mountain_route_id,
            'max_weekly_km': self.max_weekly_km,
            'max_long_run_km': self.max_long_run_km,
            'max_long_run_hours': self.max_long_run_hours,
            'available_hours_per_week': self.available_hours_per_week,
            'usual_midweek_hours': self.usual_midweek_hours,
            'max_mountain_hours_per_outing': self.max_mountain_hours_per_outing,
            'terrain_profile': self.terrain_profile,
            'terrain_profile_source': self.terrain_profile_source or 'inferred',
            'max_hours_per_day': self.max_hours_per_day,
            'strength_training_days': self.strength_training_days or 0,
            'strength_preferred_days': self.strength_preferred_days or [],
            'pace_zone_method': self.pace_zone_method or 'physics',
            'pace_zone_race_distance_m': self.pace_zone_race_distance_m,
            'pace_zone_race_time_s': self.pace_zone_race_time_s,
            'hr_max': self.hr_max,
            'hr_rest': self.hr_rest,
            'lthr': self.lthr,
            'ftp_w': self.ftp_w,
        }

    def __repr__(self):
        return f'<UserTrainingPreferences user_id={self.user_id} lr={self.long_run_day}>'

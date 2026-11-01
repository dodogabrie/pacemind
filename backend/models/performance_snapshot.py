"""Performance snapshot model for tracking user progress over time."""

from database import db
from datetime import datetime, timezone


class PerformanceSnapshot(db.Model):
    """Track user's performance calibration over time periods.

    Stores weekly/monthly snapshots of user's pace-grade curve to enable
    trend analysis and gamification features.

    Attributes:
        id: Primary key
        user_id: Foreign key to users table
        snapshot_date: Date when snapshot was created
        period_type: Type of period (weekly, monthly, quarterly)
        period_start: Start date of the period
        period_end: End date of the period
        flat_pace: User's flat terrain pace (min/km)
        anchor_ratios: Pace ratios at key grades (JSON)
        activity_count: Number of activities in period
        total_distance_km: Total distance covered in period
        total_elevation_m: Total elevation gain in period
        created_at: Timestamp of creation
    """
    __tablename__ = 'performance_snapshots'
    __table_args__ = (
        db.Index('ix_perf_snapshot_user_period', 'user_id', 'period_type', 'snapshot_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Period information
    snapshot_date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    period_type = db.Column(db.String(20), nullable=False)  # weekly, monthly, quarterly
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)

    # Performance metrics (similar to user.saved_flat_pace and saved_anchor_ratios)
    flat_pace = db.Column(db.Float, nullable=False)
    _anchor_ratios = db.Column('anchor_ratios', db.JSON, nullable=False)

    # Activity statistics for period
    activity_count = db.Column(db.Integer, nullable=False, default=0)
    total_distance_km = db.Column(db.Float, nullable=True)
    total_elevation_m = db.Column(db.Float, nullable=True)

    # Fatigue curve (adaptive based on user's max distance)
    _fatigue_curve = db.Column('fatigue_curve', db.JSON, nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    grade_performances = db.relationship('GradePerformanceHistory', backref='snapshot',
                                        lazy=True, cascade='all, delete-orphan')

    @property
    def anchor_ratios(self):
        """Get anchor_ratios.

        Returns:
            Dict mapping grade (as string) to pace ratio
            Example: {"-30": 2.5, "-20": 2.0, "0": 1.0, "30": 2.8}
        """
        if self._anchor_ratios:
            return self._anchor_ratios
        return {}

    @anchor_ratios.setter
    def anchor_ratios(self, value):
        """Store anchor_ratios.

        Args:
            value: Dict mapping grade to pace ratio
        """
        self._anchor_ratios = value if value else {}

    @property
    def fatigue_curve(self):
        """Get fatigue_curve.

        Returns:
            Dict with max_distance_km, sample_distances, and grades
        """
        return self._fatigue_curve

    @fatigue_curve.setter
    def fatigue_curve(self, value):
        """Store fatigue_curve.

        Args:
            value: Dict with fatigue curve data
        """
        self._fatigue_curve = value

    def get_period_label(self):
        """Get human-readable period label.

        Returns:
            String like "2025-W03" for weekly, "2025-01" for monthly
        """
        if self.period_type == 'weekly':
            # Get ISO week number
            week_num = self.period_start.isocalendar()[1]
            return f"{self.period_start.year}-W{week_num:02d}"
        elif self.period_type == 'monthly':
            return f"{self.period_start.year}-{self.period_start.month:02d}"
        elif self.period_type == 'quarterly':
            quarter = (self.period_start.month - 1) // 3 + 1
            return f"{self.period_start.year}-Q{quarter}"
        return str(self.snapshot_date.date())

    def is_low_confidence(self, min_activities=2):
        """Check if snapshot has low confidence due to few activities.

        Args:
            min_activities: Minimum activities for high confidence

        Returns:
            True if activity_count < min_activities
        """
        return self.activity_count < min_activities

    def to_dict(self):
        """Convert to dictionary.

        Returns:
            Dict representation suitable for JSON serialization
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'period': self.get_period_label(),
            'period_type': self.period_type,
            'start': self.period_start.isoformat(),
            'end': self.period_end.isoformat(),
            'flat_pace': self.flat_pace,
            'anchor_ratios': self.anchor_ratios,
            'activity_count': self.activity_count,
            'total_distance': self.total_distance_km,
            'total_elevation': self.total_elevation_m,
            'fatigue_curve': self.fatigue_curve,
            'low_confidence': self.is_low_confidence(),
            'created_at': self.created_at.isoformat()
        }

"""Training load service - computes ATL/CTL/TSB from Strava activity data.

Provides fitness/fatigue metrics that help the LLM agent understand
the user's current training state for race strategy advice.

Metrics:
- ATL (Acute Training Load): 7-day exponentially weighted training stress
- CTL (Chronic Training Load): 42-day exponentially weighted training stress
- TSB (Training Stress Balance): CTL - ATL (positive = fresh, negative = fatigued)

Uses existing Strava activity data (no additional API calls needed).
"""

import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from models import Activity
from config.hybrid_config import get_logger
from sqlalchemy import and_

logger = get_logger(__name__)

# TRIMP-like training impulse constants
ATL_DECAY_DAYS = 7    # Acute load window
CTL_DECAY_DAYS = 42   # Chronic load window


class TrainingLoadService:
    """Compute training load metrics from user's Strava activities."""

    def get_training_load(self, user_id: int, as_of_date: Optional[datetime] = None) -> Dict:
        """Compute ATL, CTL, TSB for a user.

        Args:
            user_id: User ID
            as_of_date: Date to compute metrics for (default: now)

        Returns:
            Dict with atl, ctl, tsb, recent_activities summary, interpretation
        """
        if as_of_date is None:
            as_of_date = datetime.now(timezone.utc)

        # Strip timezone info for comparison with naive DB datetimes
        if as_of_date.tzinfo is not None:
            as_of_date = as_of_date.replace(tzinfo=None)

        # Fetch activities from the last 60 days (enough for CTL computation)
        cutoff = as_of_date - timedelta(days=60)
        activities = (
            Activity.query
            .filter_by(user_id=user_id)
            .filter(Activity.start_date >= cutoff)
            .filter(Activity.start_date <= as_of_date)
            .order_by(Activity.start_date.desc())
            .all()
        )

        return self._compute_metrics_from_activities(activities, as_of_date)

    def get_training_load_batch(
        self,
        user_id: int,
        dates: List[datetime]
    ) -> Dict[datetime, Dict]:
        """Compute ATL/CTL/TSB going into each date (activities strictly before it).

        Fetches all activities once and computes metrics for each date.

        Args:
            user_id: User ID
            dates: List of dates to compute metrics for

        Returns:
            Dict mapping each date to its training load metrics
        """
        if not dates:
            return {}

        # Strip timezone info for comparison with naive DB datetimes
        dates = [d.replace(tzinfo=None) if d.tzinfo is not None else d for d in dates]

        # Fetch all activities covering min(dates) - 60d to max(dates)
        min_date = min(dates) - timedelta(days=60)
        max_date = max(dates)

        activities = (
            Activity.query
            .filter_by(user_id=user_id)
            .filter(Activity.start_date >= min_date)
            .filter(Activity.start_date <= max_date)
            .order_by(Activity.start_date.desc())
            .all()
        )

        # Strictly before each date: the dates are activity starts (Tier 3
        # training), and the form going INTO a run must not include that run.
        result = {}
        for target_date in dates:
            cutoff = target_date - timedelta(days=60)
            date_activities = [
                a for a in activities
                if cutoff <= a.start_date < target_date
            ]
            result[target_date] = self._compute_metrics_from_activities(
                date_activities, target_date
            )

        return result

    def _compute_metrics_from_activities(
        self,
        activities: List,
        as_of_date: datetime
    ) -> Dict:
        """Compute training load metrics from a list of activities.

        Args:
            activities: List of Activity records
            as_of_date: Reference date for computation

        Returns:
            Dict with atl, ctl, tsb, recent_activities summary, interpretation
        """
        if not activities:
            return {
                'atl': 0.0,
                'ctl': 0.0,
                'tsb': 0.0,
                'form': 'unknown',
                'recent_activities_7d': 0,
                'recent_activities_30d': 0,
                'recent_volume_km_7d': 0.0,
                'recent_volume_km_30d': 0.0,
                'recent_elevation_m_7d': 0.0,
                'interpretation': 'No recent activity data available.',
            }

        # Compute daily training impulses
        daily_load = self._compute_daily_load(activities, as_of_date)

        # Exponentially weighted moving averages
        atl = self._ewma(daily_load, ATL_DECAY_DAYS)
        ctl = self._ewma(daily_load, CTL_DECAY_DAYS)
        tsb = ctl - atl

        # Recent activity summary
        seven_days_ago = as_of_date - timedelta(days=7)
        thirty_days_ago = as_of_date - timedelta(days=30)

        recent_7d = [a for a in activities if a.start_date >= seven_days_ago]
        recent_30d = [a for a in activities if a.start_date >= thirty_days_ago]

        volume_7d = sum(a.distance / 1000 for a in recent_7d)
        volume_30d = sum(a.distance / 1000 for a in recent_30d)

        return {
            'atl': round(atl, 1),
            'ctl': round(ctl, 1),
            'tsb': round(tsb, 1),
            'form': self._interpret_tsb(tsb),
            'recent_activities_7d': len(recent_7d),
            'recent_activities_30d': len(recent_30d),
            'recent_volume_km_7d': round(volume_7d, 1),
            'recent_volume_km_30d': round(volume_30d, 1),
            'interpretation': self._full_interpretation(atl, ctl, tsb, volume_7d),
        }

    def _compute_daily_load(
        self,
        activities: List[Activity],
        as_of_date: datetime
    ) -> Dict[int, float]:
        # TODO(coach-review #56 — see GH issues): no HRV ingestion (autonomic readiness).
        # Distance + elevation TRIMP-lite is fine for chronic load but blind to acute
        # parasympathetic recovery. Add HrvReading model + Garmin Connect / Apple
        # HealthKit sync; a >1 SD drop in 7-day rMSSD baseline should flag low
        # readiness and feed plan_adjustment_service (#55, #58).
        """Compute training load per day (days-ago indexed).

        Uses a simplified TRIMP: distance_km * elevation_gain_factor.
        This isn't as accurate as HR-based TRIMP but works without HR data.

        Args:
            activities: Strava activities
            as_of_date: Reference date

        Returns:
            Dict mapping days_ago -> total_load for that day
        """
        daily = {}

        for activity in activities:
            days_ago = (as_of_date - activity.start_date).days
            if days_ago < 0:
                continue

            # Simple load estimate: distance (km) with elevation bonus
            distance_km = activity.distance / 1000 if activity.distance else 0

            # Estimate elevation gain from streams if available,
            # else the provider's figure (summary rows carry no streams)
            elevation_gain = 0
            streams = activity.streams
            if not streams:
                elevation_gain = activity.elevation_gain_m or 0
            elif 'altitude' in streams:
                alt = streams['altitude']
                alt_data = alt if isinstance(alt, list) else alt.get('data', [])
                for i in range(1, len(alt_data)):
                    diff = alt_data[i] - alt_data[i - 1]
                    if diff > 0:
                        elevation_gain += diff

            # Training load: distance with elevation weighting
            # Each 100m of climbing adds roughly 1km equivalent effort
            load = distance_km + (elevation_gain / 100.0)

            daily[days_ago] = daily.get(days_ago, 0) + load

        return daily

    def _ewma(self, daily_load: Dict[int, float], decay_days: int) -> float:
        """Compute exponentially weighted moving average.

        Args:
            daily_load: Dict mapping days_ago -> load
            decay_days: Decay constant in days

        Returns:
            EWMA value
        """
        decay = 1.0 - math.exp(-1.0 / decay_days)
        result = 0.0

        for days_ago in range(60):  # Look back 60 days max
            load = daily_load.get(days_ago, 0.0)
            weight = math.exp(-days_ago / decay_days)
            result += load * weight * decay

        # The 60-day window truncates the series: normalise so a steady load
        # reads as itself (CTL would otherwise sit at ~76 % of it).
        return result / (1.0 - math.exp(-60.0 / decay_days))

    def _interpret_tsb(self, tsb: float) -> str:
        """Interpret TSB value as training form.

        Args:
            tsb: Training Stress Balance

        Returns:
            Form description
        """
        if tsb > 15:
            return 'very_fresh'
        elif tsb > 5:
            return 'fresh'
        elif tsb > -5:
            return 'neutral'
        elif tsb > -15:
            return 'fatigued'
        else:
            return 'very_fatigued'

    def _full_interpretation(
        self,
        atl: float,
        ctl: float,
        tsb: float,
        volume_7d: float
    ) -> str:
        """Generate human-readable training load interpretation.

        Args:
            atl: Acute training load
            ctl: Chronic training load
            tsb: Training stress balance
            volume_7d: 7-day volume in km

        Returns:
            Interpretation string for the agent
        """
        # Fitness level
        if ctl > 80:
            fitness = "High fitness level"
        elif ctl > 50:
            fitness = "Good fitness level"
        elif ctl > 25:
            fitness = "Moderate fitness level"
        else:
            fitness = "Building fitness"

        # Freshness
        form = self._interpret_tsb(tsb)
        form_map = {
            'very_fresh': "very well-rested (good for racing)",
            'fresh': "fresh and ready to perform",
            'neutral': "balanced — neither fatigued nor fully rested",
            'fatigued': "carrying some fatigue from recent training",
            'very_fatigued': "significantly fatigued — consider recovery before racing",
        }
        form_desc = form_map.get(form, "unknown status")

        # Volume context
        if volume_7d > 80:
            vol_desc = f"Heavy training week ({volume_7d:.0f}km)"
        elif volume_7d > 50:
            vol_desc = f"Moderate-high training week ({volume_7d:.0f}km)"
        elif volume_7d > 25:
            vol_desc = f"Moderate training week ({volume_7d:.0f}km)"
        elif volume_7d > 0:
            vol_desc = f"Light training week ({volume_7d:.0f}km)"
        else:
            vol_desc = "No recent training"

        return f"{fitness}. Currently {form_desc}. {vol_desc}."

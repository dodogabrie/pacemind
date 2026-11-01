"""Adaptive Strava-history capacity inference."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.training_capacity_inference import (
    HIGH_MIN_ACTIVITIES,
    HIGH_MIN_WEEKS,
    infer_capacity,
)


def _activity(days_ago: int, hours: float, elev_m: float = 0.0,
              hour_offset: int = 8):
    """Build a fake Activity-like object."""
    start = datetime.now(timezone.utc) - timedelta(days=days_ago,
                                                   hours=hour_offset)
    streams = {'time': [0, hours * 3600.0]}
    return SimpleNamespace(
        start_date=start,
        streams=streams,
        _streams=streams,
        total_elevation_gain=elev_m,
    )


def _loader_factory(activities_by_window):
    """Return a loader that returns the right list per `since_dt` cutoff."""
    def loader(user_id, since_dt):
        return [a for a in activities_by_window
                if a.start_date >= since_dt]
    return loader


class TestConfidenceLevels:
    def test_high_confidence_with_dense_history(self):
        # 5 activities/week for 10 weeks = 50 activities, 10 weeks.
        acts = []
        for week in range(10):
            for d in range(5):
                acts.append(_activity(week * 7 + d, hours=1.0))
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        assert result['confidence'] == 'high'
        assert result['sample_size_activities'] >= HIGH_MIN_ACTIVITIES
        assert result['sample_size_weeks'] >= HIGH_MIN_WEEKS
        assert result['fallback_used'] is False
        assert result['available_hours_per_week'] >= 4.0

    def test_medium_confidence_with_sparse_history(self):
        # 3 activities/week for 5 weeks = 15 activities.
        acts = []
        for week in range(5):
            for d in range(3):
                acts.append(_activity(week * 7 + d, hours=1.0))
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        assert result['confidence'] == 'medium'
        assert result['fallback_used'] is False

    def test_low_confidence_falls_back_to_defaults(self):
        # Just 3 activities total — far below MEDIUM threshold.
        acts = [_activity(d, hours=1.0) for d in (1, 8, 15)]
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        assert result['confidence'] == 'low'
        assert result['fallback_used'] is True
        assert result['available_hours_per_week'] == 4.0
        assert result['max_long_run_hours'] == 2.0

    def test_no_activities_returns_low_confidence(self):
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory([]))
        assert result['confidence'] == 'low'
        assert result['fallback_used'] is True


class TestAdaptiveLookback:
    def test_lookback_expands_when_recent_history_is_sparse(self):
        # No activities in last 12 weeks; plenty in weeks 30-40.
        acts = []
        for week in range(30, 42):
            for d in range(4):
                acts.append(_activity(week * 7 + d, hours=1.5))
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        # Should have expanded past 12 weeks to find samples.
        assert result['lookback_weeks_used'] >= 24
        # And found enough for at least medium confidence.
        assert result['confidence'] in ('medium', 'high')

    def test_lookback_caps_at_52_weeks(self):
        # Activities only from > 1 year ago — should not pick them up.
        acts = [_activity(400 + d * 5, hours=1.0) for d in range(20)]
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        assert result['lookback_weeks_used'] <= 52


class TestMountainInference:
    def test_mountain_activities_classified(self):
        acts = []
        # 8 mountain runs (>= 300m) over 8 weeks.
        for week in range(8):
            acts.append(_activity(week * 7, hours=3.0, elev_m=800))
        # Plus 24 flat runs to reach high confidence.
        for week in range(8):
            for d in range(1, 4):
                acts.append(_activity(week * 7 + d, hours=1.0, elev_m=10))
        result = infer_capacity(user_id=1, _activity_loader=_loader_factory(acts))
        assert result['mountain_runs_per_week'] > 0
        assert result['usual_mountain_hours'] >= 2.0

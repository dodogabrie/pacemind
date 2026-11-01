"""Tests for PassiveReadinessService — TSB-driven fallback for missing check-ins.

Covers the three gates that decide whether a synthetic check-in is produced
(coach-review #55):

  G1. recent_activities_30d < 5  → None (CTL too noisy to act on)
  G2. tsb >= threshold           → None (athlete is fresh enough)
  G3. tsb <  threshold           → SyntheticCheckin(is_bad_day=True, source='tsb_low')
"""

from __future__ import annotations

from datetime import date

import pytest

from services.passive_readiness_service import (
    DEFAULT_TSB_BAD_THRESHOLD,
    MIN_RECENT_ACTIVITIES,
    PassiveReadinessService,
    SyntheticCheckin,
)


class _StubLoadService:
    """Test double — returns a canned training-load payload."""

    def __init__(self, payload):
        self.payload = payload
        self.last_call = None

    def get_training_load(self, user_id, as_of_date=None):
        self.last_call = (user_id, as_of_date)
        return self.payload


def _payload(tsb: float, recent_30d: int = 12) -> dict:
    return {
        'atl': 50.0,
        'ctl': 50.0 + tsb,  # not used by the service, just for realism
        'tsb': tsb,
        'recent_activities_30d': recent_30d,
        'recent_activities_7d': max(0, recent_30d // 3),
    }


def test_low_tsb_produces_synthetic_checkin():
    """G3: tsb below threshold → bad-day synthetic checkin."""
    svc = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-20.0))
    )
    result = svc.compute_synthetic_checkin(user_id=1, target_date=date(2026, 5, 20))
    assert isinstance(result, SyntheticCheckin)
    assert result.is_bad_day is True
    assert result.source == 'tsb_low'
    assert result.synthetic is True
    assert 0.5 <= result.confidence <= 1.0


def test_neutral_tsb_returns_none():
    """G2: tsb above threshold → no signal, no adjustment."""
    svc = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-5.0))
    )
    assert svc.compute_synthetic_checkin(user_id=1, target_date=date(2026, 5, 20)) is None


def test_cold_start_returns_none():
    """G1: fewer than MIN_RECENT_ACTIVITIES → CTL unreliable, return None even
    if tsb looks bad."""
    svc = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-30.0, recent_30d=3))
    )
    assert svc.compute_synthetic_checkin(user_id=1, target_date=date(2026, 5, 20)) is None


def test_threshold_is_inclusive_above():
    """Exactly at threshold = not bad day. Threshold gate uses strict ``<``."""
    svc = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=DEFAULT_TSB_BAD_THRESHOLD)),
    )
    assert svc.compute_synthetic_checkin(user_id=1) is None


def test_custom_threshold_overrides_default():
    """Coaches can tighten the gate by passing threshold=-10."""
    svc = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-12.0)),
        threshold=-10.0,
    )
    result = svc.compute_synthetic_checkin(user_id=1)
    assert result is not None and result.is_bad_day is True


def test_confidence_grows_with_distance_from_threshold():
    """Confidence scales with how fatigued the athlete looks."""
    mild = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-15.5))
    ).compute_synthetic_checkin(user_id=1)
    severe = PassiveReadinessService(
        training_load_service=_StubLoadService(_payload(tsb=-30.0))
    ).compute_synthetic_checkin(user_id=1)
    assert mild is not None and severe is not None
    assert severe.confidence > mild.confidence


def test_load_service_exception_swallowed():
    """If TrainingLoadService blows up we degrade to None, not raise."""

    class _Boom:
        def get_training_load(self, *args, **kwargs):
            raise RuntimeError('boom')

    svc = PassiveReadinessService(training_load_service=_Boom())
    assert svc.compute_synthetic_checkin(user_id=1) is None


def test_min_recent_activities_constant_documented():
    """Guardrail: if we ever lower MIN_RECENT_ACTIVITIES below 5 the
    threshold gate becomes noise. Pin the constant so the intent stays
    visible in code review."""
    assert MIN_RECENT_ACTIVITIES == 5

"""Smoke tests for the Session 5 audit fixes in PerformanceTracker.

These tests cover the concrete bugs fixed in `services/performance_tracker.py`:
  - `_streams_have_data` correctly distinguishes empty-on-failure dicts.
  - `compare_periods` does not raise ZeroDivisionError when the older
    snapshot has flat_pace == 0.
  - `compare_periods` tolerates snapshots whose `anchor_ratios` JSON is None.
  - `award_achievements` rolls back and returns [] on commit failure.
  - `_check_personal_record` accepts a pre-filtered list (no DB query needed).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.performance_tracker import (
    PerformanceTracker,
    _streams_have_data,
)


def test_streams_have_data_rejects_empty_failure_payload():
    # download_streams returns this on transport error / non-200.
    failure_payload = {
        "time": [], "altitude": [], "grade_smooth": [],
        "velocity_smooth": [], "heartrate": [], "cadence": [],
        "moving": [], "distance": [],
    }
    assert _streams_have_data(failure_payload) is False


def test_streams_have_data_accepts_real_payload():
    payload = {"distance": [0, 1, 2], "velocity_smooth": [3.0, 3.1, 3.2]}
    assert _streams_have_data(payload) is True


def test_streams_have_data_rejects_none_or_non_dict():
    assert _streams_have_data(None) is False
    assert _streams_have_data([]) is False
    assert _streams_have_data("nope") is False
    assert _streams_have_data({}) is False


def _tracker():
    return PerformanceTracker(
        cache_service=MagicMock(),
        strava_service=MagicMock(),
        user_repo=MagicMock(),
        performance_repo=MagicMock(),
        achievement_repo=MagicMock(),
    )


def test_compare_periods_zero_flat_pace_does_not_divide_by_zero():
    tracker = _tracker()
    s1 = SimpleNamespace(flat_pace=5.0, anchor_ratios={})
    s2 = SimpleNamespace(flat_pace=0.0, anchor_ratios={})

    changes = tracker.compare_periods(s1, s2)

    assert changes['flat_pace'] == 5.0
    assert changes['flat_pace_pct'] == 0
    assert changes['grades'] == {}


def test_compare_periods_tolerates_none_anchor_ratios():
    tracker = _tracker()
    s1 = SimpleNamespace(flat_pace=5.0, anchor_ratios=None)
    s2 = SimpleNamespace(flat_pace=5.5, anchor_ratios=None)

    changes = tracker.compare_periods(s1, s2)

    assert 'grades' in changes
    assert changes['grades'] == {}


def test_award_achievements_rolls_back_on_commit_failure():
    tracker = _tracker()
    sentinel = SimpleNamespace(id=None, achievement_name='test')
    tracker.detect_achievements = MagicMock(return_value=[sentinel])
    tracker.achievement_repo.commit.side_effect = RuntimeError("db down")

    result = tracker.award_achievements(user_id=42)

    assert result == []
    tracker.achievement_repo.rollback.assert_called_once()


def test_award_achievements_returns_empty_when_no_new_achievements():
    tracker = _tracker()
    tracker.detect_achievements = MagicMock(return_value=[])

    result = tracker.award_achievements(user_id=42)

    assert result == []
    tracker.achievement_repo.commit.assert_not_called()
    tracker.achievement_repo.rollback.assert_not_called()


def test_check_personal_record_uses_passed_in_list_without_querying():
    tracker = _tracker()
    current = SimpleNamespace(
        id=99,
        flat_pace=5.0,
        anchor_ratios={"10": 1.2},
    )
    historical = SimpleNamespace(
        snapshot_id=1, grade_bucket=10, median_pace=7.0, avg_pace=7.0
    )
    older = SimpleNamespace(
        snapshot_id=2, grade_bucket=10, median_pace=8.0, avg_pace=8.0
    )

    achievement = tracker._check_personal_record(
        user_id=1, grade=10, recent_snapshots=[current],
        all_grade_perfs=[historical, older],
    )

    # Repo must NOT have been touched — bug was N+1 from per-grade query.
    tracker.performance_repo.get_grade_performances.assert_not_called()
    assert achievement is not None
    assert achievement.achievement_type == 'pr'

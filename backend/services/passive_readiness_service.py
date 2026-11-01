"""Passive readiness fallback when DailyCheckin is missing.

Coach-review #55: the daily check-in is the primary signal driving
``services.plan_adjustment_service``. If the user doesn't log it the swap /
downgrade rules never fire and the plan can't react to a fatigued athlete.

This service derives a *synthetic* check-in from objective signals already
in the system — currently TSB from ``TrainingLoadService`` — so the
intra-week swap still triggers even without an explicit check-in. The
output duck-types ``models.DailyCheckin`` (it only needs to expose
``is_bad_day``).

Conservative-by-design:
  - Synthetic check-ins fire only the *swap* rule, never the *downgrade*
    rule. Stripping intensity off a quality session on a noisy TSB signal
    is hard to undo and would erode trust quickly. The downgrade gate stays
    on explicit two-day-in-a-row real check-ins.
  - With < ``MIN_RECENT_ACTIVITIES`` runs in the last 30 days CTL is too
    noisy to act on, so we return ``None`` (no signal → no adjustment).
  - The threshold is configurable per-deployment via
    ``PASSIVE_READINESS_TSB_THRESHOLD``.

Citations:
  - Coggan, A. R. — Performance Manager Chart: TSB < -10 / -15 marks the
    fatigued / very-fatigued bands where the next quality session is risky.
  - Halson, S. L. (2014). *Monitoring training load to understand fatigue
    in athletes*. Sports Med — objective load complements subjective measures.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TSB_BAD_THRESHOLD = -15.0
MIN_RECENT_ACTIVITIES = 5


@dataclass
class SyntheticCheckin:
    """Duck-typed stand-in for ``DailyCheckin``.

    ``PlanAdjustmentService`` only reads ``is_bad_day``; ``source`` /
    ``confidence`` / ``synthetic`` flow through to the notification text
    so the user understands the plan moved without an explicit check-in.
    """

    is_bad_day: bool
    source: str
    confidence: float = 0.6
    synthetic: bool = True


class PassiveReadinessService:
    """Derive a ``SyntheticCheckin`` from objective training load signals."""

    def __init__(self, training_load_service=None, threshold: Optional[float] = None):
        if training_load_service is None:
            from services.training_load_service import TrainingLoadService
            training_load_service = TrainingLoadService()
        self.load_svc = training_load_service
        self.threshold = (
            threshold
            if threshold is not None
            else float(os.getenv('PASSIVE_READINESS_TSB_THRESHOLD', DEFAULT_TSB_BAD_THRESHOLD))
        )

    def compute_synthetic_checkin(
        self, user_id: int, target_date: Optional[date] = None
    ) -> Optional[SyntheticCheckin]:
        """Return a ``SyntheticCheckin`` if the athlete looks fatigued, else
        ``None``.

        ``None`` is NOT "feeling good" — it's "no actionable signal". The
        caller must treat it as a no-op, not as a green light.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).date()
        as_of = datetime.combine(target_date, time.max).replace(tzinfo=timezone.utc)

        try:
            load = self.load_svc.get_training_load(user_id, as_of_date=as_of)
        except Exception as e:
            logger.warning("Passive readiness: TSB lookup failed for user %s: %s", user_id, e)
            return None

        if not load:
            return None
        if load.get('recent_activities_30d', 0) < MIN_RECENT_ACTIVITIES:
            return None

        tsb = load.get('tsb', 0.0)
        if tsb >= self.threshold:
            return None

        # Confidence scales with how far past the threshold we are; capped at 1.0.
        # threshold = -15, tsb = -15 → 0.5; tsb = -20 → 1.0; tsb = -25 → 1.0.
        confidence = min(1.0, abs(tsb - self.threshold) / 10.0 + 0.5)
        return SyntheticCheckin(
            is_bad_day=True,
            source='tsb_low',
            confidence=round(confidence, 2),
        )

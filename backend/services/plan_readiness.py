"""Pre-flight readiness assessment for training plan generation.

Compares the athlete's current capacity against the race demands and
returns a verdict — ``feasible``, ``stretch`` or ``unrealistic`` — plus
the reasons and a recommended minimum number of weeks. The race-add API
and the agent's ``generate_full_plan`` tool refuse to build plans when
the verdict is ``unrealistic`` (unless the caller passes ``force``) and
surface alternatives instead.

Pure assessment functions plus thin DB helpers. The bulk of the logic
is functional and covered by unit tests; the helpers (``get_athlete_baseline``,
``suggest_alternative_races``) wrap optional DB calls in try/except so
they degrade gracefully when Strava data or the race calendar is empty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from services.plan_engine import (
    LONG_RUN_BASELINE_MULTIPLIER,
    LONG_RUN_PEAK_FRACTION,
)

# Verdict thresholds ----------------------------------------------------------
# ``stretch`` = doable with caveats; the engine's baseline cap will clip
# the peak LR to ~2× current. ``unrealistic`` = jump too large to bridge
# even with clipping; we refuse and propose alternatives.
LR_STRETCH_MULTIPLIER = LONG_RUN_BASELINE_MULTIPLIER       # > this  → stretch
LR_UNREALISTIC_MULTIPLIER = 4.0                             # > this  → refuse

# CTL target, in the same km-effort/day units as TrainingLoadService.ctl
# (km + D+/100): chronic weekly load >= CTL_WEEKLY_RACE_MULTIPLE x the race
# distance. The race's D+ is not known here, so its km is the (lower) proxy.
CTL_WEEKLY_RACE_MULTIPLE = 1.5
CTL_UNREALISTIC_RATIO = 0.6   # ctl < 60 % of target  → refuse
CTL_STRETCH_RATIO     = 0.8   # ctl < 80 % of target  → stretch

# Min-weeks model -------------------------------------------------------------
# Each "step" of long-run progression bumps ~10 % week-over-week. With
# 3:1 modulation (3 progression weeks per recovery), we need roughly
# ``ceil(log(ratio)/log(1.10)) * 1.25`` calendar weeks to bridge the
# baseline → peak gap, plus 2 weeks Base, 2 weeks taper, 1 race week.
_PROGRESSION_STEP = 1.10
_PROGRESSION_CALENDAR_FACTOR = 1.25
_BASE_BLOCK_WEEKS = 2
_TAPER_WEEKS = 2
_RACE_WEEK = 1
ABSOLUTE_MIN_WEEKS = 2  # below this we always refuse; engine returns ['Race']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctl_target_for(race_distance_km: float) -> float:
    return CTL_WEEKLY_RACE_MULTIPLE * race_distance_km / 7.0


def min_weeks_for_race(
    race_distance_km: float,
    athlete_longest_run_km: float,
) -> int:
    """Minimum recommended weeks for the athlete to bridge their baseline
    to the race-day long-run target safely."""
    target_lr = race_distance_km * LONG_RUN_PEAK_FRACTION
    if athlete_longest_run_km > 0:
        effective_peak = min(target_lr,
                             LONG_RUN_BASELINE_MULTIPLIER * athlete_longest_run_km)
        ratio = max(1.0, effective_peak / athlete_longest_run_km)
    else:
        # No baseline known — assume conservatively that the user starts
        # near zero and needs the full progression window.
        ratio = LONG_RUN_BASELINE_MULTIPLIER

    if ratio <= 1.01:
        progression_weeks = 2
    else:
        steps = math.ceil(math.log(ratio) / math.log(_PROGRESSION_STEP))
        progression_weeks = max(2, int(round(steps * _PROGRESSION_CALENDAR_FACTOR)))

    return progression_weeks + _BASE_BLOCK_WEEKS + _TAPER_WEEKS + _RACE_WEEK


def weeks_until(race_date) -> int:
    """Whole calendar weeks from today until ``race_date``. Accepts date,
    datetime or ISO-8601 string."""
    if race_date is None:
        return 0
    if isinstance(race_date, str):
        try:
            race_date = datetime.fromisoformat(race_date).date()
        except ValueError:
            return 0
    if isinstance(race_date, datetime):
        race_date = race_date.date()

    delta = (race_date - date.today()).days
    if delta <= 0:
        return 0
    return max(1, delta // 7)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass
class ReadinessVerdict:
    status: str  # 'feasible' | 'stretch' | 'unrealistic'
    reasons: list[str] = field(default_factory=list)
    available_weeks: int = 0
    min_weeks_recommended: int = 0
    long_run_jump_ratio: float = 0.0
    target_peak_long_run_km: float = 0.0
    ctl: Optional[float] = None
    ctl_target: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'status': self.status,
            'reasons': list(self.reasons),
            'available_weeks': self.available_weeks,
            'min_weeks_recommended': self.min_weeks_recommended,
            'long_run_jump_ratio': round(self.long_run_jump_ratio, 2),
            'target_peak_long_run_km': round(self.target_peak_long_run_km, 1),
            'ctl': self.ctl,
            'ctl_target': self.ctl_target,
        }


def _escalate(current: str, candidate: str) -> str:
    """'unrealistic' beats 'stretch' beats 'feasible'."""
    order = {'feasible': 0, 'stretch': 1, 'unrealistic': 2}
    return current if order[current] >= order[candidate] else candidate


def assess_readiness(
    *,
    race_distance_km: float,
    available_weeks: int,
    athlete_longest_run_km: float,
    athlete_weekly_km: float = 0.0,
    ctl: Optional[float] = None,
) -> ReadinessVerdict:
    """Verdict on whether the athlete can safely race in ``available_weeks``.

    When neither the long-run baseline nor CTL are known we err on the
    permissive side (only the absolute-minimum-window gate fires) so a
    user who hasn't connected Strava yet can still add a race. Once data
    flows in, the agent can re-assess on the next plan generation.
    """
    reasons: list[str] = []
    status = 'feasible'

    target_lr = race_distance_km * LONG_RUN_PEAK_FRACTION
    has_lr_baseline = athlete_longest_run_km > 0
    if has_lr_baseline:
        lr_ratio = target_lr / athlete_longest_run_km
    else:
        lr_ratio = float('inf') if target_lr > 0 else 0.0

    min_weeks = min_weeks_for_race(race_distance_km, athlete_longest_run_km)
    ctl_target = _ctl_target_for(race_distance_km)
    has_evidence = has_lr_baseline or ctl is not None

    # Long-run jump --------------------------------------------------------
    if not has_lr_baseline:
        reasons.append('long_run_baseline_unknown')
    elif lr_ratio > LR_UNREALISTIC_MULTIPLIER:
        status = _escalate(status, 'unrealistic')
        reasons.append(
            f"long_run_jump_too_large (lungo attuale "
            f"{athlete_longest_run_km:.1f} km, target ~{target_lr:.1f} km, "
            f"jump {lr_ratio:.1f}×)"
        )
    elif lr_ratio > LR_STRETCH_MULTIPLIER:
        status = _escalate(status, 'stretch')
        reasons.append(
            f"long_run_jump_above_safe_cap (target {target_lr:.1f} km vs "
            f"attuale {athlete_longest_run_km:.1f} km, salto {lr_ratio:.1f}× "
            f"— rischio infortunio elevato, valuta una gara più corta o "
            f"più tempo)"
        )

    # Available time -------------------------------------------------------
    if available_weeks < ABSOLUTE_MIN_WEEKS:
        status = _escalate(status, 'unrealistic')
        reasons.append(
            f"plan_window_too_short (disponibili {available_weeks}, "
            f"minimo assoluto {ABSOLUTE_MIN_WEEKS})"
        )
    elif has_evidence and available_weeks < min_weeks:
        # Only fire the progression-window gate when we have evidence
        # the athlete can't bridge it. Without evidence we can't tell.
        gap = min_weeks - available_weeks
        if gap >= 4:
            status = _escalate(status, 'unrealistic')
        else:
            status = _escalate(status, 'stretch')
        reasons.append(
            f"insufficient_weeks (disponibili {available_weeks}, "
            f"minimo consigliato {min_weeks})"
        )

    # Chronic load ---------------------------------------------------------
    if ctl is not None and ctl >= 0:
        if ctl < ctl_target * CTL_UNREALISTIC_RATIO:
            status = _escalate(status, 'unrealistic')
            reasons.append(
                f"low_chronic_load (CTL {ctl:.0f} vs target {ctl_target:.0f} "
                f"per {race_distance_km:.0f} km)"
            )
        elif ctl < ctl_target * CTL_STRETCH_RATIO:
            status = _escalate(status, 'stretch')
            reasons.append(
                f"chronic_load_below_target (CTL {ctl:.0f} vs {ctl_target:.0f})"
            )

    return ReadinessVerdict(
        status=status,
        reasons=reasons,
        available_weeks=available_weeks,
        min_weeks_recommended=min_weeks,
        long_run_jump_ratio=lr_ratio if lr_ratio != float('inf') else 99.0,
        target_peak_long_run_km=target_lr,
        ctl=ctl,
        ctl_target=ctl_target,
    )


# ---------------------------------------------------------------------------
# Optional DB-backed helpers
# ---------------------------------------------------------------------------

def get_athlete_baseline(user_id: int, *, lookback_days: int = 120) -> dict:
    """Best-effort snapshot of the athlete's recent training capacity.

    Returns ``{longest_run_km, weekly_km, ctl, source}`` where missing
    components are ``None``. The caller (typically the readiness gate)
    treats ``None`` longest_run_km as 'unknown' and falls back to user
    prefs (``max_long_run_km``).
    """
    longest_run_km: Optional[float] = None
    weekly_km: Optional[float] = None
    ctl: Optional[float] = None
    sources: list[str] = []

    try:
        from models import Activity

        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        rows = (
            Activity.query
            .filter_by(user_id=user_id)
            .filter(Activity.start_date >= cutoff)
            .all()
        )
        if rows:
            sources.append('strava')
            longest_run_km = max((a.distance or 0) for a in rows) / 1000.0
    except Exception:
        rows = []

    try:
        from services.training_load_service import TrainingLoadService
        tl = TrainingLoadService().get_training_load(user_id)
        # TrainingLoadService returns ctl=0.0 when there are zero recent
        # activities; treat that as "unknown" rather than "sedentary" so
        # the readiness gate doesn't refuse plans for users who simply
        # haven't connected Strava yet. The long-run baseline gate still
        # applies when prefs supply max_long_run_km.
        if (tl.get('recent_activities_30d') or 0) > 0:
            ctl = tl.get('ctl')
        v30 = tl.get('recent_volume_km_30d')
        if v30:
            weekly_km = float(v30) / 4.0
            if 'strava' not in sources:
                sources.append('training_load')
    except Exception:
        pass

    return {
        'longest_run_km': longest_run_km,
        'weekly_km': weekly_km,
        'ctl': ctl,
        'source': ','.join(sources) if sources else 'none',
    }


def suggest_alternative_races(
    *,
    race_distance_km: float,
    athlete_longest_run_km: float,
    after_date: Optional[date] = None,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    max_travel_km: Optional[float] = None,
    limit: int = 3,
) -> list[dict]:
    """Propose shorter races within reach of the athlete's current baseline.

    The peak LR cap is ``2 × longest_run`` (or 5 km floor if unknown);
    the corresponding race distance is roughly ``cap / 0.75``.
    """
    floor_km = max(athlete_longest_run_km, 5.0)
    safe_peak_lr = LONG_RUN_BASELINE_MULTIPLIER * floor_km
    safe_race_max_km = max(5.0, safe_peak_lr / LONG_RUN_PEAK_FRACTION)
    # Don't bother suggesting something longer than (or equal to) the
    # original — the whole point is to pick something shorter.
    if safe_race_max_km >= race_distance_km:
        return []

    try:
        from repositories.race_repository import RaceRepository
        repo = RaceRepository()
        rows = repo.search(
            start_date=after_date or date.today(),
            min_distance_km=max(5.0, safe_race_max_km * 0.4),
            max_distance_km=safe_race_max_km,
            near_lat=near_lat,
            near_lon=near_lon,
            max_travel_km=max_travel_km,
            sort='date',
            limit=max(limit * 2, 5),
        )
    except Exception:
        return []

    out: list[dict] = []
    for r in rows[:limit]:
        out.append({
            'id': r.id,
            'slug': getattr(r, 'slug', None),
            'name': r.name,
            'date': r.date.isoformat() if r.date else None,
            'distance_km': r.distance_km,
            'elev_gain_m': r.elev_gain_m,
            'reason': 'shorter_race_within_safe_progression',
        })
    return out

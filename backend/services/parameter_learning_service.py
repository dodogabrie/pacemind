"""
Parameter learning service for Tier 2 predictions.

Calibrates the physics model on the user's most recent run streams
(`calibrate_user_params` measures flat speed, uphill and downhill directly)
and measures its own accuracy walk-forward, so the displayed interval is the
error the model actually made on the user's past runs. The same walk-forward
rows feed the personal race/training ratio and Tier 3 (residual_ml_service.py).
"""

import math
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from models import Activity, UserLearnedParams, UserActivityResidual
from repositories import UserLearnedParamsRepository
from services.physics_prediction_service import PhysicsPredictionService
from services.physics_model.calibration import calibrate_user_params
from services.residual_ml_service import ResidualMLService, attach_bins, race_ratio
from services.physics_model.pipeline import DEFAULT_FATIGUE_ALPHA
from services import intensity_service
from config.hybrid_config import get_logger, DEFAULT_PARAMS, TIER_2_MIN_ACTIVITIES, TIER3_ENABLED

logger = get_logger(__name__)

CALIBRATION_WINDOW = 10
"""Most recent eligible activities used for the fit (frozen; do not tune on the backtest)."""

RUN_SPORT_TYPES = ('run', 'trail_run')
REQUIRED_STREAMS = ('distance', 'velocity_smooth', 'grade_smooth', 'altitude')
MIN_DISTANCE_M = 3000
QUALITY_MAX_RATIO = 1.75
"""Drop activities whose km-effort pace is > 1.75x the median (paused watch, hike, corrupt moving time)."""

STOP_SHARE_MAX = 0.15


def _residual_key(a: Activity) -> str:
    # Same key as ActivityIngestService._residual_activity_id.
    return str(a.strava_id) if a.strava_id else f'{a.source}_{a.id}'


def _km_effort_pace(a: Activity) -> float:
    return a.moving_time_s / (a.distance / 1000 + (a.elevation_gain_m or 0) / 100)


def _candidates(user_id: int):
    return Activity.query.filter(
        Activity.user_id == user_id,
        Activity.sport_type.in_(RUN_SPORT_TYPES),
        Activity.distance >= MIN_DISTANCE_M,
        Activity.moving_time_s > 0,
        Activity._streams.isnot(None),
    )


def count_stream_runs(user_id: Optional[int]) -> int:
    """Cheap upper bound of eligible_activities (no stream parsing, no quality rule)."""
    return _candidates(user_id).count() if user_id else 0


def eligible_activities(user_id: int, before: Optional[datetime] = None) -> List[Activity]:
    """Run activities with full streams the fitter may use, oldest first."""
    q = _candidates(user_id)
    if before is not None:
        q = q.filter(Activity.start_date < before)
    excluded = {
        r.activity_id for r in
        UserActivityResidual.query.filter_by(user_id=user_id, excluded_from_training=True)
    }
    acts = [
        a for a in q.order_by(Activity.start_date).all()
        if _residual_key(a) not in excluded and all(k in a.streams for k in REQUIRED_STREAMS)
    ]
    return quality_filter(acts)


def quality_filter(acts: List[Activity]) -> List[Activity]:
    if not acts:
        return acts
    median = float(np.median([_km_effort_pace(a) for a in acts]))
    return [a for a in acts if _km_effort_pace(a) <= QUALITY_MAX_RATIO * median]


def fit_params(activities: List[Activity]) -> Dict[str, float]:
    """Physics params calibrated on the last CALIBRATION_WINDOW activities."""
    # TODO(pred-review #104 — see GH issues): replace this point estimate with
    # hierarchical personal params (population prior on params only) and a
    # posterior interval; the empirical interval below covers the UI need now.
    window = activities[-CALIBRATION_WINDOW:]
    dfs = PhysicsPredictionService().prepare_streams_for_calibration([a.streams for a in window])
    # float(): calibration returns numpy scalars, which psycopg2 cannot bind.
    params = {k: float(v) for k, v in calibrate_user_params(dfs).items()}
    params['fatigue_alpha'] = DEFAULT_FATIGUE_ALPHA
    return params


def stop_share(activities: List[Activity]) -> float:
    """Median passive-stop share (elapsed-moving)/moving over the fit window."""
    shares = [
        (a.elapsed_time_s - a.moving_time_s) / a.moving_time_s
        for a in activities[-CALIBRATION_WINDOW:] if a.elapsed_time_s
    ]
    if not shares:
        return 0.0
    return float(min(STOP_SHARE_MAX, max(0.0, np.median(shares))))


def track_points(a: Activity) -> List[Dict]:
    s = a.streams
    return [{'distance': float(d), 'elevation': float(z)} for d, z in zip(s['distance'], s['altitude'])]


def walk_forward(activities: List[Activity], min_prior: int = TIER_2_MIN_ACTIVITIES) -> List[Dict]:
    """Every activity with >= min_prior predecessors, predicted from params
    fitted ONLY on the (up to 10) activities strictly before it.

    One row per activity: {activity, is_race, physics (the Tier 2 result on its
    own track), log_error = log(actual_moving / predicted)}. Tier 2 takes its
    interval from the last 20 errors, Tier 3 learns from the physics segments."""
    physics = PhysicsPredictionService()
    rows = []
    for i in range(min_prior, len(activities)):
        a = activities[i]
        params = fit_params(activities[max(0, i - CALIBRATION_WINDOW):i])
        res = physics.predict(track_points(a), params, user_id=None)
        if res.get('total_time_seconds'):
            rows.append({'activity': a, 'is_race': bool(getattr(a, 'is_race', False)), 'physics': res,
                         'log_error': math.log(a.moving_time_s / res['total_time_seconds'])})
    return rows


def intensity_model(user_id: Optional[int], acts: List[Activity], params: Dict, rows: List[Dict]) -> Optional[Dict]:
    """HR speed-vs-intensity model (services/intensity_service.py) + the user's race
    intensity offset from races with HR. None without enough HR data (-> old path)."""
    hr_max, hr_rest = intensity_service.profile_hr(user_id) if user_id else (None, None)
    model = intensity_service.fit(acts, params, hr_max, hr_rest, ref_activities=acts[-CALIBRATION_WINDOW:])
    if model is None:
        return None
    races = []
    for r in rows:
        if r['is_race']:
            i = intensity_service.observed_intensity(r['activity'].streams, params, model)
            if i:
                races.append({'intensity': i, 'hours': r['activity'].moving_time_s / 3600})
    model.update(race_offset=intensity_service.race_offset(races), n_races_hr=len(races),
                 efforts=intensity_service.efforts(acts, params, model))
    return model


def prediction_interval(log_errors: Optional[List[float]], tier: str) -> Tuple[float, float]:
    """(lo, hi) multipliers of the predicted finish for an 80 % interval."""
    if tier == 'TIER_1_PHYSICS':
        return 0.75, 1.25  # Tier 1 P80 |err| was 26 % in the backtest
    if log_errors and len(log_errors) >= 8:
        # Split-conformal order statistics, not np.quantile(0.1/0.9): with n=20
        # the plain sample quantiles cover ~72 % in expectation (backtest: 66 %
        # moving / 63 % elapsed); these ranks give >= 80 % (backtest: 79 / 76 %).
        s, n = sorted(log_errors), len(log_errors)
        lo_rank = max(1, math.floor((n + 1) * 0.1))
        hi_rank = min(n, math.ceil((n + 1) * 0.9))
        return math.exp(s[lo_rank - 1]), math.exp(s[hi_rank - 1])
    return 0.80, 1.20


def accuracy(log_errors: Optional[List[float]]) -> Optional[Dict]:
    """P80 of |relative error| on past runs, for the 'within ±X% 8 times out of 10' label."""
    if not log_errors or len(log_errors) < 8:
        return None
    rel = np.abs(np.exp(log_errors) - 1)
    return {'p80_pct': int(round(100 * float(np.quantile(rel, 0.8)))), 'n': len(log_errors)}


class ParameterLearningService:
    """Tier 2: physics params calibrated on the user's recent runs."""

    def __init__(self, learned_params_repo=None):
        self.learned_params_repo = learned_params_repo or UserLearnedParamsRepository()

    def train_user_params(self, user_id: int) -> Optional[UserLearnedParams]:
        try:
            started = datetime.now(timezone.utc)
            acts = eligible_activities(user_id)
            if len(acts) < TIER_2_MIN_ACTIVITIES:
                logger.warning(f"User {user_id} has only {len(acts)} eligible activities (need {TIER_2_MIN_ACTIVITIES})")
                return None

            params = fit_params(acts)
            rows = walk_forward(acts)
            errors = [r['log_error'] for r in rows[-20:]]
            uncertainties = {
                'stop_share': stop_share(acts),
                'log_errors': errors,
                'race_ratio': race_ratio(rows),
                'intensity': intensity_model(user_id, acts, params, rows),
                'n_eval': len(errors),
                'window_activity_ids': [a.id for a in acts[-CALIBRATION_WINDOW:]],
            }
            score = float(np.median(np.abs(errors))) if errors else None
            n_used = min(len(acts), CALIBRATION_WINDOW)

            learned_params = self.learned_params_repo.get_for_user(user_id)
            if learned_params:
                for key, value in params.items():
                    setattr(learned_params, key, value)
                learned_params.n_activities_used = n_used
                learned_params.optimization_score = score
                learned_params.param_uncertainties = uncertainties
                learned_params.last_trained = datetime.now(timezone.utc)
                learned_params.version = (learned_params.version or 1) + 1
            else:
                learned_params = UserLearnedParams(
                    user_id=user_id, **params, n_activities_used=n_used,
                    optimization_score=score, param_uncertainties=uncertainties,
                )
                self.learned_params_repo.create(learned_params)

            self.learned_params_repo.commit()
            logger.info(
                f"Tier 2 params for user {user_id}: v_flat={params['v_flat']:.2f} k_up={params['k_up']:.2f} "
                f"n_eval={len(errors)} in {(datetime.now(timezone.utc) - started).total_seconds():.1f}s"
            )
        except Exception as e:
            logger.exception(f"Error training parameters for user {user_id}: {e}")
            self.learned_params_repo.rollback()
            return None

        if TIER3_ENABLED:
            # Tier 3 reuses the same walk-forward rows; a failure never costs the Tier 2 params.
            try:
                ResidualMLService().train_from_rows(user_id, attach_bins(user_id, rows))
            except Exception as e:
                logger.exception(f"Tier 3 training failed for user {user_id}: {e}")
                self.learned_params_repo.rollback()
        return learned_params

    def get_user_params(self, user_id: int) -> Optional[Dict[str, float]]:
        learned_params = self.learned_params_repo.get_for_user(user_id)
        return learned_params.to_dict() if learned_params else None

    def get_or_default_params(self, user_id: int) -> Dict[str, float]:
        params = self.get_user_params(user_id)
        return params if params else DEFAULT_PARAMS.copy()


_retrain_lock = threading.Lock()
_retrain_pending: Dict[int, bool] = {}  # user_id -> another run requested while training


def train_async(user_id: int) -> None:
    """Retrain Tier 2 (+ Tier 3) in a background thread; calls that arrive
    mid-training coalesce into one more run, so the last change is never lost."""
    # ponytail: per-process; with several gunicorn workers two runs can overlap
    # (last writer wins, same data). Move to a job queue if that ever matters.
    with _retrain_lock:
        if user_id in _retrain_pending:
            _retrain_pending[user_id] = True
            return
        _retrain_pending[user_id] = False

    def work():
        from app import create_app
        with create_app().app_context():
            while True:
                ParameterLearningService().train_user_params(user_id)
                with _retrain_lock:
                    if not _retrain_pending[user_id]:
                        del _retrain_pending[user_id]
                        return
                    _retrain_pending[user_id] = False

    threading.Thread(target=work, daemon=True).start()

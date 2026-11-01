"""Hybrid prediction service - picks the physics parameters for a user.

- Tier 1: physics with default parameters (fewer than 5 eligible runs)
- Tier 2: physics calibrated on the user's last 10 runs, with an interval
  measured walk-forward on the user's own runs
- Tier 3: Tier 2 x personal per-200 m corrections learned walk-forward
  (services/residual_ml_service.py), used only for users whose own walk-forward
  shows it beats Tier 2 (the gate); everyone else stays on Tier 2.

Finish = moving time x effort + passive stops (learned share) + aid stops.

Privacy-compliant: Only uses individual user's own activity data.
"""

from typing import Dict, List, Optional

from repositories import UserLearnedParamsRepository, UserResidualModelRepository
from services.physics_prediction_service import PhysicsPredictionService
from services.parameter_learning_service import (
    ParameterLearningService,
    accuracy,
    count_stream_runs,
    prediction_interval,
)
from services.intensity_service import moving_at_effort, moving_at_hr
from services.residual_ml_service import ResidualMLService, bin_multipliers, course_bins, SEGMENT_LENGTH_M, PHYSICS_STEP_M
from config.hybrid_config import get_logger, DEFAULT_PARAMS, TIER_2_MIN_ACTIVITIES, TIER3_ENABLED
from utils.formatting import format_seconds_to_hms_padded

logger = get_logger(__name__)

TIER_1 = 'TIER_1_PHYSICS'
TIER_2 = 'TIER_2_PARAMETER_LEARNING'
TIER_3 = 'TIER_3_RESIDUAL_ML'

# Fallback when the user has no heart-rate data: 'race' uses the learned
# race/training ratio (param_uncertainties['race_ratio'], shrunk toward 0.95).
EFFORT_FACTORS = {'race': 0.95, 'training': 1.0, 'recovery': 1.05}


class HybridPredictionService:
    """Orchestrates predictions across tiers."""

    def __init__(self, learned_params_repo=None, residual_model_repo=None):
        self.physics_service = PhysicsPredictionService()
        self.parameter_service = ParameterLearningService()
        self.learned_params_repo = learned_params_repo or UserLearnedParamsRepository()
        self.residual_model_repo = residual_model_repo or UserResidualModelRepository()
        self.ml_service = ResidualMLService(self.residual_model_repo)

    def predict(
        self,
        user_id: Optional[int],
        gpx_points: List[Dict],
        force_tier: Optional[str] = None,
        include_diagnostics: bool = False,
        effort: str = 'training',
        aid_stops: Optional[Dict] = None,
        target_hr: Optional[float] = None,
    ) -> Dict:
        """Predict route time.

        Args:
            user_id: User ID (None for anonymous demo)
            gpx_points: Route points [{distance, elevation}, ...]
            force_tier: 'physics' forces Tier 1 defaults; 'parameter_learning' is the default path
            include_diagnostics: Include detailed diagnostics in response
            effort: 'race' / 'training' / 'recovery' -> a heart-rate intensity when the
                user has HR data (services/intensity_service.py); else x0.95 (or the
                learned race ratio) / x1 / x1.05
            aid_stops: optional {'count': int, 'minutes_each': float}
            target_hr: optional bpm the user plans to hold; overrides `effort` and adds
                a sustainability verdict (needs HR data, else ignored)

        Returns:
            Physics result where total_time_seconds is the finish (moving + stops),
            plus moving_time_seconds, stop_time_seconds, confidence_interval, metadata.
        """
        tier = TIER_1 if force_tier == 'physics' else self._determine_tier(user_id)
        if tier == TIER_3 and force_tier == 'parameter_learning':
            tier = TIER_2

        record = None
        if tier in (TIER_2, TIER_3):
            record = self.learned_params_repo.get_for_user(user_id)
            if not record:
                logger.info(f"No learned params for user {user_id}, training Tier 2...")
                record = self.parameter_service.train_user_params(user_id)
            if not record:
                tier = TIER_1
        params = record.to_dict() if record else DEFAULT_PARAMS.copy()

        result = self.physics_service.predict(gpx_points, params, user_id=user_id)
        if 'error' in result:
            return result

        stats = (record.param_uncertainties or {}) if record else {}
        log_errors = stats.get('log_errors')
        if tier == TIER_3:
            t3_errors = self._apply_tier3(user_id, result)
            if t3_errors is None:
                tier = TIER_2
            else:
                log_errors = t3_errors

        # Effort -> intensity from heart rate when the user has HR data; else the
        # fixed factors, with the learned race/training ratio for 'race'.
        intensity = None
        if stats.get('intensity'):
            if target_hr:
                intensity = moving_at_hr(stats['intensity'], target_hr, result['total_time_seconds'])
            else:
                intensity = moving_at_effort(stats['intensity'], effort, result['total_time_seconds'])
            factor = intensity['moving_s'] / result['total_time_seconds']
        else:
            factor = EFFORT_FACTORS.get(effort, 1.0)
            if effort == 'race':
                factor = (stats.get('race_ratio') or {}).get('ratio', factor)
        if factor != 1.0:
            for seg in result['segments']:
                seg['time_s'] *= factor
                seg['pace_min_km'] *= factor
        moving = result['total_time_seconds'] * factor
        aid = aid_stops or {}
        stops = moving * stats.get('stop_share', 0.0) + aid.get('count', 0) * aid.get('minutes_each', 0) * 60
        finish = moving + stops

        lo, hi = prediction_interval(log_errors, tier)
        result.update(
            total_time_seconds=finish,
            total_time_formatted=format_seconds_to_hms_padded(finish),
            moving_time_seconds=moving,
            stop_time_seconds=stops,
            confidence_interval={
                'lower_seconds': finish * lo,
                'upper_seconds': finish * hi,
                'lower_formatted': format_seconds_to_hms_padded(finish * lo),
                'upper_formatted': format_seconds_to_hms_padded(finish * hi),
            },
        )

        n = record.n_activities_used if record else 0
        result['metadata'] = {
            'tier': tier,
            'method': {TIER_1: 'physics_baseline', TIER_2: 'physics_personalized',
                       TIER_3: 'physics_personal_habits'}[tier],
            'activities_used': n,
            'accuracy': accuracy(log_errors),
            'personal_model': self.personal_model_status(user_id),
            'race_ratio': factor if effort == 'race' else None,
            'intensity': {k: intensity[k] for k in ('intensity', 'hr_low', 'hr_high', 'target_hr', 'verdict')
                          if k in intensity} | {'hr_max': stats['intensity']['hr_max'],
                                                'hr_rest': stats['intensity']['hr_rest']} if intensity else None,
            'description': {TIER_1: 'Physics model with default parameters',
                            TIER_2: f'Physics model calibrated on your last {n} runs',
                            TIER_3: 'Physics model calibrated on your runs plus your own pacing habits'}[tier],
        }

        if include_diagnostics:
            result['diagnostics'] = {
                'tier': tier,
                'learned_params': params,
                'optimization_score': record.optimization_score if record else None,
                'stop_share': stats.get('stop_share'),
                'effort_factor': factor,
            }

        return result

    def _apply_tier3(self, user_id: int, result: Dict) -> Optional[List[float]]:
        """Scale the physics segments by the user's per-200 m multipliers.
        Returns the Tier 3 walk-forward log errors (for the interval), or None
        when there is no usable model (then the caller stays on Tier 2)."""
        bundle = self.ml_service.get_bundle(user_id)
        if bundle is None:
            return None
        try:
            from services.training_load_service import TrainingLoadService
            tsb = TrainingLoadService().get_training_load(user_id).get('tsb', 0.0)
        except Exception as e:
            logger.warning(f"No fitness for Tier 3 (user {user_id}): {e}")
            tsb = 0.0
        mult = bin_multipliers(bundle, course_bins(result, tsb))
        k = SEGMENT_LENGTH_M // PHYSICS_STEP_M
        for b, m in enumerate(mult):
            for seg in result['segments'][b * k:(b + 1) * k]:
                seg['time_s'] *= m
                seg['pace_min_km'] *= m
        result['total_time_seconds'] = float(sum(s['time_s'] for s in result['segments']))
        return self.residual_model_repo.get_for_user(user_id).metrics.get('t3_log_errors')

    def personal_model_status(self, user_id: Optional[int]) -> Optional[Dict]:
        """Is the personal-habits model in use, and why (for the UI)."""
        if not user_id or not TIER3_ENABLED:
            return None
        rec = self.residual_model_repo.get_for_user(user_id)
        m = (rec.metrics or {}) if rec else {}
        if 'reason' not in m:  # never trained, or the pre-rebuild GBM row
            return {'active': False, 'reason': 'not_enough_history', 'n_eval': 0}
        keys = ('reason', 'n_eval', 'mape_t2', 'mape_t3', 'bias_t2', 'bias_t3', 'habits', 'race_ratio')
        return {'active': bool(m.get('open')), **{k: m.get(k) for k in keys}}

    def _determine_tier(self, user_id: Optional[int]) -> str:
        if not user_id:
            return TIER_1
        if TIER3_ENABLED and (self.personal_model_status(user_id) or {}).get('active'):
            return TIER_3
        if self.learned_params_repo.get_for_user(user_id):
            return TIER_2
        return TIER_2 if count_stream_runs(user_id) >= TIER_2_MIN_ACTIVITIES else TIER_1

    def get_user_tier_status(self, user_id: int) -> Dict:
        """Current tier, progress to Tier 2 and measured accuracy."""
        record = self.learned_params_repo.get_for_user(user_id)
        activity_count = count_stream_runs(user_id)
        current_tier = self._determine_tier(user_id)
        needed = max(0, TIER_2_MIN_ACTIVITIES - activity_count) if current_tier == TIER_1 else 0
        errors = (record.param_uncertainties or {}).get('log_errors') if record else None
        if current_tier == TIER_3:
            errors = self.residual_model_repo.get_for_user(user_id).metrics.get('t3_log_errors')

        return {
            'current_tier': current_tier,
            'activity_count': activity_count,
            'next_tier': TIER_2 if current_tier == TIER_1 else None,
            'activities_needed_for_next_tier': needed,
            'progress_to_next_tier_pct': round(min(100, activity_count / TIER_2_MIN_ACTIVITIES * 100), 1),
            'has_learned_params': record is not None,
            'last_trained': record.last_trained.isoformat() if record else None,
            'accuracy': accuracy(errors),
            'personal_model': self.personal_model_status(user_id),
        }

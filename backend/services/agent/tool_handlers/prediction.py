"""Prediction-related handlers: run, compare, retrain, tier status."""

from typing import Dict, Any

from config.hybrid_config import get_logger, DEFAULT_PARAMS
from models.agent_param_snapshot import AgentParamSnapshot
from repositories import UserLearnedParamsRepository, GPXFileRepository
from services.hybrid_prediction_service import HybridPredictionService
from services.parameter_learning_service import ParameterLearningService
from services.physics_prediction_service import PhysicsPredictionService

logger = get_logger(__name__)


def _handle_get_tier_status(tool_input: Dict, user_id: int) -> Dict:
    """Get user's tier status and progress."""
    service = HybridPredictionService()
    return service.get_user_tier_status(user_id)


def _handle_run_prediction(tool_input: Dict, user_id: int) -> Dict:
    """Run prediction on a GPX route."""
    gpx_id = tool_input.get('gpx_id')
    effort = tool_input.get('effort', 'race')

    if not gpx_id:
        return {'error': 'gpx_id is required'}

    # Verify GPX belongs to user
    gpx_repo = GPXFileRepository()
    gpx_file = gpx_repo.get_user_file(gpx_id, user_id)
    if not gpx_file or not gpx_file.data:
        return {'error': f'GPX route {gpx_id} not found'}

    points = gpx_file.data.get('points', [])
    if not points:
        return {'error': 'GPX route has no points'}

    service = HybridPredictionService()
    result = service.predict(
        user_id=user_id,
        gpx_points=points,
        include_diagnostics=True,
        effort=effort,
    )

    if 'error' in result:
        return result

    # Summarize for agent (full segment list would be too large)
    total_time = result.get('total_time_seconds', 0)
    h = int(total_time // 3600)
    m = int((total_time % 3600) // 60)
    s = int(total_time % 60)

    segments = result.get('segments', [])
    total_distance_km = (segments[-1]['distance_m'] + segments[-1]['length_m']) / 1000 if segments else 0
    total_elevation = sum(
        seg.get('length_m', 0) * seg.get('grade', 0)
        for seg in segments if seg.get('grade', 0) > 0
    )

    return {
        'total_time_formatted': f"{h}:{m:02d}:{s:02d}",
        'total_time_seconds': total_time,
        'total_distance_km': round(total_distance_km, 2),
        'total_elevation_gain_m': round(total_elevation, 0),
        'effort': effort,
        'metadata': result.get('metadata', {}),
        'confidence_interval': result.get('confidence_interval'),
        'n_segments': len(segments),
    }


def _handle_compare_predictions(tool_input: Dict, user_id: int) -> Dict:
    """Compare predictions with two parameter sets."""
    gpx_id = tool_input.get('gpx_id')
    params_a = tool_input.get('params_a', {})
    params_b = tool_input.get('params_b', {})

    if not gpx_id:
        return {'error': 'gpx_id is required'}

    gpx_repo = GPXFileRepository()
    gpx_file = gpx_repo.get_user_file(gpx_id, user_id)
    if not gpx_file or not gpx_file.data:
        return {'error': f'GPX route {gpx_id} not found'}

    points = gpx_file.data.get('points', [])
    if not points:
        return {'error': 'GPX route has no points'}

    # Fill missing params with defaults
    full_a = DEFAULT_PARAMS.copy()
    full_a.update(params_a)
    full_b = DEFAULT_PARAMS.copy()
    full_b.update(params_b)

    physics_service = PhysicsPredictionService()

    result_a = physics_service.predict(points, full_a, user_id=user_id)
    result_b = physics_service.predict(points, full_b, user_id=user_id)

    if 'error' in result_a or 'error' in result_b:
        return {'error': 'Prediction failed', 'details': {
            'a': result_a.get('error'),
            'b': result_b.get('error'),
        }}

    time_a = result_a.get('total_time_seconds', 0)
    time_b = result_b.get('total_time_seconds', 0)
    diff = time_b - time_a
    pct = (diff / time_a * 100) if time_a > 0 else 0

    def fmt(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        return f"{h}:{m:02d}:{s:02d}"

    return {
        'params_a': full_a,
        'params_b': full_b,
        'time_a': {'seconds': time_a, 'formatted': fmt(time_a)},
        'time_b': {'seconds': time_b, 'formatted': fmt(time_b)},
        'difference': {
            'seconds': diff,
            'formatted': fmt(abs(diff)),
            'percent': round(pct, 2),
            'direction': 'faster' if diff < 0 else 'slower',
        },
    }


def _handle_retrain_model(tool_input: Dict, user_id: int) -> Dict:
    """Retrain the physics params; the personal-habits model (Tier 3) retrains with them."""
    param_service = ParameterLearningService()
    AgentParamSnapshot.create_snapshot(
        user_id=user_id,
        params=param_service.get_or_default_params(user_id),
        action='retrain_model',
        description='Retrain params',
    )

    trained = param_service.train_user_params(user_id)
    if not trained:
        return {'tier2': {'success': False, 'error': 'Training failed or insufficient data'}}
    trained.manually_adjusted = False
    UserLearnedParamsRepository().commit()
    return {
        'tier2': {
            'success': True,
            'new_params': trained.to_dict(),
            'optimization_score': trained.optimization_score,
            'n_activities': trained.n_activities_used,
        },
        'personal_model': HybridPredictionService().personal_model_status(user_id),
    }

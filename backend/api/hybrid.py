"""Hybrid prediction API endpoints.

Unified prediction API using tiered approach:
- Tier 1: Physics baseline
- Tier 2: Physics calibrated on the user's last 10 runs
- Tier 3: Tier 2 + personal per-200 m habits, only where the user's own walk-forward shows it helps
"""

import json

import numpy as np
from flask import Blueprint, request, jsonify
from models import Prediction
from repositories import (
    GPXFileRepository, PredictionRepository, UserActivityResidualRepository
)
from api.utils import get_current_user
from api.validation import (
    validate_predict_request,
    validate_gpx_points,
    create_error_response,
    log_validation_error,
)
from services.hybrid_prediction_service import HybridPredictionService
from services.parameter_learning_service import train_async
from config.hybrid_config import get_logger
from utils.formatting import (
    format_seconds_to_hms_padded,
    format_seconds_to_hms,
    v_flat_to_pace,
)

logger = get_logger(__name__)

bp = Blueprint('hybrid', __name__, url_prefix='/api/hybrid')

gpx_repo = GPXFileRepository()
prediction_repo = PredictionRepository()
residual_repo = UserActivityResidualRepository()


class _NumpyEncoder(json.JSONEncoder):
    """Convert numpy types to native Python for JSON/DB serialization."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _sanitize(obj):
    """Round-trip through JSON to convert all numpy types to native Python."""
    return json.loads(json.dumps(obj, cls=_NumpyEncoder))


# ---------------------------------------------------------------------------
# Prediction helpers (extracted from predict())
# ---------------------------------------------------------------------------

def _extract_flat_pace(result: dict) -> float:
    """Extract flat pace (min/km) from prediction result, with fallback."""
    if 'user_params' in result:
        v_flat = result['user_params'].get('v_flat')
        if v_flat:
            return v_flat_to_pace(v_flat)

    if 'diagnostics' in result and 'learned_params' in result['diagnostics']:
        v_flat = result['diagnostics']['learned_params'].get('v_flat')
        if v_flat:
            return v_flat_to_pace(v_flat)

    return 6.0  # Default


def _format_segments(segments: list[dict]) -> list[dict]:
    """Transform raw segments to frontend format with cumulative time."""
    formatted = []
    cumulative_time = 0

    for seg in segments:
        cumulative_time += seg.get('time_s', 0)

        distance_m = seg.get('distance_m', 0)
        length_m = seg.get('length_m', 0)
        grade = seg.get('grade', 0)
        avg_pace = seg.get('pace_min_km', 6.0)

        formatted.append({
            'distance_m': distance_m,
            'length_m': length_m,
            'grade': grade,
            'time_s': seg.get('time_s', 0),
            'pace_min_km': avg_pace,
            # Frontend-expected fields
            'start_km': round(distance_m / 1000.0, 2),
            'end_km': round((distance_m + length_m) / 1000.0, 2),
            'avg_grade_percent': round(grade * 100, 1),
            'avg_pace_min_per_km': round(avg_pace, 2),
            'time_formatted': format_seconds_to_hms(cumulative_time),
        })

    return formatted


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@bp.route('/tier-status', methods=['GET'])
def get_tier_status():
    """Get user's current prediction tier and progress."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    hybrid_service = HybridPredictionService()
    status = hybrid_service.get_user_tier_status(user.id)
    return jsonify(status)


@bp.route('/predict', methods=['POST'])
def predict():
    """Unified hybrid prediction endpoint.

    Body: {
        "gpx_id": 123,
        "force_tier": "parameter_learning",  // Optional
        "include_diagnostics": true,         // Optional
        "effort": "training",                // Optional: race, training, recovery
        "aid_stops": {"count": 8, "minutes_each": 3}  // Optional
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return create_error_response({'request': 'Request body must be JSON'})

    is_valid, errors = validate_predict_request(data)
    if not is_valid:
        log_validation_error('/api/hybrid/predict', errors)
        return create_error_response(errors)

    gpx_id = data['gpx_id']
    force_tier = data.get('force_tier')
    include_diagnostics = data.get('include_diagnostics', False)
    effort = data.get('effort', 'training')

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)
    if not gpx_file or not gpx_file.data:
        return jsonify({'error': 'GPX file not found'}), 404

    points = gpx_file.data.get('points', [])
    is_valid, error_msg = validate_gpx_points(points)
    if not is_valid:
        logger.warning(f"Invalid GPX points for file {gpx_id}: {error_msg}")
        return jsonify({'error': error_msg}), 400

    try:
        hybrid_service = HybridPredictionService()
        result = hybrid_service.predict(
            user_id=user.id,
            gpx_points=points,
            force_tier=force_tier,
            include_diagnostics=include_diagnostics,
            effort=effort,
            aid_stops=data.get('aid_stops'),
            target_hr=data.get('target_hr'),
        )

        if 'error' in result:
            return jsonify(result), 500

        metadata = result.get('metadata', {})
        segments = result.get('segments', [])

        flat_pace = _extract_flat_pace(result)

        # Calculate elevation gain from segments (uphill only)
        total_elevation_gain = sum(
            seg.get('length_m', 0) * seg.get('grade', 0)
            for seg in segments
            if seg.get('grade', 0) > 0
        )

        total_time_sec = float(result['total_time_seconds'])
        formatted_segments = _format_segments(segments)

        formatted_prediction = {
            'total_time_seconds': total_time_sec,
            'total_time_formatted': format_seconds_to_hms_padded(total_time_sec),
            'moving_time_seconds': float(result.get('moving_time_seconds', total_time_sec)),
            'stop_time_seconds': float(result.get('stop_time_seconds', 0.0)),
            'confidence_interval': result['confidence_interval'],
            'segments': formatted_segments,
            'raw_segments': formatted_segments,
            'statistics': {
                'total_distance_km': formatted_segments[-1]['end_km'] if formatted_segments else 0,
                'total_elevation_gain_m': total_elevation_gain,
                'flat_pace_min_per_km': flat_pace,
            },
            'metadata': metadata,
        }

        db_prediction = Prediction(
            user_id=user.id,
            gpx_file_id=gpx_file.id,
            flat_pace=flat_pace,
            user_fingerprint={
                'tier': metadata.get('tier'),
                'method': metadata.get('method'),
                'activities_used': metadata.get('activities_used'),
            },
            total_time_seconds=total_time_sec,
            predicted_segments=_sanitize(formatted_segments),
        )
        prediction_repo.create(db_prediction)
        prediction_repo.commit()

        return jsonify({
            'prediction_id': db_prediction.id,
            'prediction': formatted_prediction,
            'metadata': metadata,
            'diagnostics': result.get('diagnostics') if include_diagnostics else None,
        })

    except Exception as e:
        prediction_repo.rollback()
        logger.exception(f"Error in API endpoint: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@bp.route('/training-activities', methods=['GET'])
def get_training_activities():
    """Get list of downloaded activities with training status."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    activities = residual_repo.get_user_residuals(user.id)

    activity_list = [{
        'id': act.id,
        'activity_id': act.activity_id,
        'activity_date': act.activity_date.isoformat(),
        'distance_km': act.total_distance_km,
        'elevation_gain_m': act.total_elevation_gain_m,
        'activity_type': act.activity_type,
        'segment_count': act.segment_count,
        'excluded_from_training': act.excluded_from_training,
        'recency_weight': act.recency_weight,
    } for act in activities]

    return jsonify({
        'activities': activity_list,
        'total': len(activity_list),
        'included_count': sum(1 for a in activity_list if not a['excluded_from_training']),
        'excluded_count': sum(1 for a in activity_list if a['excluded_from_training']),
    })


@bp.route('/training-activities/<int:residual_id>/toggle', methods=['POST'])
def toggle_activity_training(residual_id):
    """Toggle whether an activity is included in training."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    residual = residual_repo.get_user_residual(residual_id, user.id)
    if not residual:
        return jsonify({'error': 'Activity not found'}), 404

    residual.excluded_from_training = not residual.excluded_from_training
    residual_repo.commit()

    logger.info(
        f"Activity {residual.activity_id} "
        f"{'excluded from' if residual.excluded_from_training else 'included in'} "
        f"training for user {user.id}"
    )

    return jsonify({
        'success': True,
        'activity_id': residual.activity_id,
        'excluded_from_training': residual.excluded_from_training,
    })


@bp.route('/train-ml-model', methods=['POST'])
def train_ml_model():
    """Recalibrate the user's params and personal-habits model in the background."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    train_async(user.id)
    return jsonify({'started': True}), 202

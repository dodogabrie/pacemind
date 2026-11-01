import logging

from flask import Blueprint, request, jsonify, current_app
from services.physics_prediction_service import PhysicsPredictionService
from services.strava_service import StravaService
from services.cache_service import CacheService
from models import Prediction
from repositories import UserRepository, GPXFileRepository, PredictionRepository
from api.utils import get_current_user
from utils.formatting import (
    format_seconds_to_hms,
    v_flat_to_pace,
    pace_to_v_flat,
    classify_terrain,
)
from utils.constants import ELEVATION_THRESHOLD_M
from services.parameter_learning_service import prediction_interval

logger = logging.getLogger(__name__)

bp = Blueprint('physics', __name__, url_prefix='/api/physics')

user_repo = UserRepository()
gpx_repo = GPXFileRepository()
prediction_repo = PredictionRepository()


def get_physics_service() -> PhysicsPredictionService:
    """Get or create physics service via Flask app context (thread-safe)."""
    if 'physics_service' not in current_app.extensions:
        current_app.extensions['physics_service'] = PhysicsPredictionService()
    return current_app.extensions['physics_service']


def get_strava_service() -> StravaService:
    return StravaService(
        current_app.config['STRAVA_CLIENT_ID'],
        current_app.config['STRAVA_CLIENT_SECRET'],
        current_app.config['STRAVA_REDIRECT_URI']
    )


def get_cache_service() -> CacheService:
    return CacheService()


# ---------------------------------------------------------------------------
# Segment aggregation helpers (extracted from predict())
# ---------------------------------------------------------------------------

def aggregate_to_200m_segments(segments: list[dict]) -> list[dict]:
    """Aggregate 50m physics segments into ~200m segments to match ML model."""
    if not segments:
        return []

    aggregated = []
    current_batch = []
    batch_start_dist = 0

    for seg in segments:
        if not current_batch:
            batch_start_dist = seg['distance_m']
            current_batch = [seg]
        else:
            batch_length = seg['distance_m'] + seg['length_m'] - batch_start_dist
            if batch_length >= 200:
                aggregated.append(_finalize_batch(current_batch, batch_start_dist))
                batch_start_dist = seg['distance_m']
                current_batch = [seg]
            else:
                current_batch.append(seg)

    if current_batch:
        aggregated.append(_finalize_batch(current_batch, batch_start_dist))

    return aggregated


def _finalize_batch(batch: list[dict], batch_start_dist: float) -> dict:
    """Summarize a batch of segments into one aggregated segment."""
    total_time = sum(s['time_s'] for s in batch)
    total_dist = sum(s['length_m'] for s in batch)
    avg_grade = (
        sum(s['grade'] * s['length_m'] for s in batch) / total_dist
        if total_dist > 0 else 0
    )
    return {
        'distance_m': batch_start_dist,
        'length_m': total_dist,
        'grade': avg_grade,
        'time_s': total_time,
        'pace_min_km': (total_time / (total_dist / 1000)) / 60 if total_dist > 0 else 0,
    }


def group_segments_by_gradient(
    segments: list[dict],
    gradient_threshold: float = 5.0,
    max_segment_length: float = 5000,
    sign_change_min_grade: float = 2.0,
) -> list[list[dict]]:
    """Group segments by grade changes.

    Args:
        segments: List of ~200m segments.
        gradient_threshold: Grade change threshold in % to trigger a split.
        max_segment_length: Max length of a group in meters.
        sign_change_min_grade: Minimum grade % to trigger sign-change split.

    Returns:
        List of segment groups (each group is a list of segments).
    """
    if not segments:
        return []

    grouped: list[list[dict]] = []
    current_group = [segments[0]]
    current_start = segments[0]['distance_m']

    for i in range(1, len(segments)):
        prev = segments[i - 1]
        curr = segments[i]

        prev_grade = prev['grade'] * 100
        curr_grade = curr['grade'] * 100

        grade_change = abs(curr_grade - prev_grade)
        sign_change = (
            (prev_grade * curr_grade < 0)
            and (abs(prev_grade) > sign_change_min_grade or abs(curr_grade) > sign_change_min_grade)
        )
        current_length = curr['distance_m'] - current_start

        should_split = (
            grade_change > gradient_threshold
            or sign_change
            or current_length > max_segment_length
        )

        if should_split:
            grouped.append(current_group)
            current_group = [curr]
            current_start = curr['distance_m']
        else:
            current_group.append(curr)

    if current_group:
        grouped.append(current_group)

    return grouped


def _format_segment_groups(segment_groups: list[list[dict]]) -> list[dict]:
    """Convert grouped segments into the frontend-compatible format."""
    ml_segments = []
    cumulative_time = 0

    for split_num, group in enumerate(segment_groups, 1):
        group_time = sum(s['time_s'] for s in group)
        group_dist = sum(s['length_m'] for s in group)
        avg_grade = sum(s['grade'] for s in group) / len(group)
        avg_pace = group_time / (group_dist / 1000) / 60

        cumulative_time += group_time
        start_km = group[0]['distance_m'] / 1000
        end_km = (group[-1]['distance_m'] + group[-1]['length_m']) / 1000

        ml_segments.append({
            'split_number': split_num,
            'segment_km': int(end_km),
            'start_km': round(start_km, 2),
            'end_km': round(end_km, 2),
            'avg_grade_percent': round(avg_grade * 100, 1),
            'avg_pace_min_per_km': round(avg_pace, 2),
            'time_formatted': format_seconds_to_hms(cumulative_time),
            'terrain': classify_terrain(avg_grade),
            'distance_m': round(group_dist, 1),
        })

    return ml_segments


def _calculate_elevation_gain(result: dict, points: list[dict]) -> float:
    """Calculate total elevation gain from resampled elevations or raw points."""
    if 'resampled_elevations' in result:
        elevations = result['resampled_elevations']
        return float(sum(
            max(0, elevations[i] - elevations[i - 1])
            for i in range(1, len(elevations))
            if abs(elevations[i] - elevations[i - 1]) >= ELEVATION_THRESHOLD_M
        ))

    # Fallback to raw points
    total = 0.0
    if points and len(points) > 1:
        for i in range(1, len(points)):
            elev_change = points[i].get('elevation', 0) - points[i - 1].get('elevation', 0)
            if abs(elev_change) >= ELEVATION_THRESHOLD_M and elev_change > 0:
                total += elev_change
    return total


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@bp.route('/calibrate', methods=['POST'])
def calibrate():
    """Calibrate from a single activity (ML-compatible format).

    Body: { "activity_id": 123 }

    Returns ML-compatible format with flat_pace_min_per_km.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    activity_id = data.get('activity_id')

    if not activity_id:
        return jsonify({'error': 'activity_id required'}), 400

    strava_service = get_strava_service()
    cache_service = get_cache_service()
    physics_service = get_physics_service()

    # Refresh token if needed
    if user.access_token:
        try:
            access_token, refresh_token, expires_at = strava_service.get_valid_token(
                user.access_token, user.refresh_token, user.expires_at
            )
            if access_token != user.access_token:
                user.access_token = access_token
                user.refresh_token = refresh_token
                user.expires_at = expires_at
                user_repo.commit()
        except Exception:
            return jsonify({'error': 'Strava auth failed'}), 401
    else:
        return jsonify({'error': 'User not connected to Strava'}), 401

    # Fetch streams for the activity
    streams = cache_service.get_cached_streams(user.id, activity_id)
    if not streams:
        try:
            streams = strava_service.download_streams(activity_id, user.access_token)
        except Exception as e:
            return jsonify({'error': f'Failed to fetch activity streams: {str(e)}'}), 400

    if not streams:
        return jsonify({'error': 'No streams available for this activity'}), 400

    try:
        params = physics_service.calibrate([streams])
        flat_pace_min_per_km = v_flat_to_pace(params['v_flat'])

        user.physics_params = params
        user_repo.commit()

        return jsonify({
            'flat_pace_min_per_km': flat_pace_min_per_km,
            'anchor_ratios': {
                '-30': params['k_terrain_down'],
                '-20': params['k_terrain_down'],
                '-10': params['k_terrain_down'],
                '0': params['k_terrain_flat'],
                '10': params['k_up'],
                '20': params['k_up'],
                '30': params['k_up'],
            },
            'diagnostics': {
                'method': 'physics_model',
                'params': params,
            },
            'activity': {
                'id': activity_id,
                'name': f'Activity {activity_id}',
                'distance_km': streams.get('distance', [0])[-1] / 1000 if streams.get('distance') else 0,
            },
        })
    except Exception:
        logger.exception("Physics calibration failed")
        return jsonify({'error': 'Calibration failed'}), 500


@bp.route('/predict', methods=['POST'])
def predict():
    """Predict route time using Physics Model (ML-compatible format).

    Body: {
        "gpx_id": 123,
        "flat_pace_min_per_km": 5.0,
        "anchor_ratios": {...},
        "cached_activities": [...],
        "split_level": 5
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    gpx_id = data.get('gpx_id')
    flat_pace_min_per_km = data.get('flat_pace_min_per_km')
    cached_activities = data.get('cached_activities', [])
    split_level = data.get('split_level', 5)

    logger.debug(f"Received split_level from frontend: {split_level}")

    if not gpx_id:
        return jsonify({'error': 'gpx_id required'}), 400
    if not flat_pace_min_per_km:
        return jsonify({'error': 'flat_pace_min_per_km required'}), 400

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)
    if not gpx_file or not gpx_file.data:
        return jsonify({'error': 'GPX not found'}), 404

    points = gpx_file.data.get('points', [])

    # Get physics params from user profile or reconstruct from flat pace
    if hasattr(user, 'physics_params') and user.physics_params:
        user_params = user.physics_params
    else:
        v_flat = pace_to_v_flat(flat_pace_min_per_km)
        user_params = {
            'v_flat': v_flat,
            'k_up': 1.0,
            'k_tech': 1.0,
            'a_param': 3.0,
            'k_terrain_up': 1.08,
            'k_terrain_down': 1.12,
            'k_terrain_flat': 1.05,
        }

    physics_service = get_physics_service()
    result = physics_service.predict(points, user_params, user_id=user.id)

    if 'error' in result:
        return jsonify(result), 500

    # Aggregate and group segments
    total_time_sec = result['total_time_seconds']
    segments_200m = aggregate_to_200m_segments(result['segments'])
    logger.debug(f"Raw 50m→{len(segments_200m)} 200m segments")

    raw_segments_for_frontend = [
        {k: seg[k] for k in ('distance_m', 'length_m', 'grade', 'time_s', 'pace_min_km')}
        for seg in segments_200m
    ]

    # Default grouped segments for backward compatibility
    segment_groups = group_segments_by_gradient(segments_200m, 3.0, 5000, 3.0)
    ml_segments = _format_segment_groups(segment_groups)

    total_elevation_gain = _calculate_elevation_gain(result, points)

    # Uncalibrated interval: same width as Tier 1 (P80 |err| 26 % in the backtest).
    lo, hi = prediction_interval(None, 'TIER_1_PHYSICS')
    ci_lower, ci_upper = total_time_sec * lo, total_time_sec * hi

    prediction = {
        'total_time_seconds': total_time_sec,
        'total_time_formatted': format_seconds_to_hms(total_time_sec),
        'confidence_interval': {
            'lower_seconds': ci_lower,
            'upper_seconds': ci_upper,
            'lower_formatted': format_seconds_to_hms(ci_lower),
            'upper_formatted': format_seconds_to_hms(ci_upper),
        },
        'segments': ml_segments,
        'raw_segments': raw_segments_for_frontend,
        'statistics': {
            'total_distance_km': result['segments'][-1]['distance_m'] / 1000 if result['segments'] else 0,
            'total_elevation_gain_m': float(total_elevation_gain),
            'avg_grade_percent': sum(s['avg_grade_percent'] for s in ml_segments) / len(ml_segments) if ml_segments else 0,
            'flat_pace_min_per_km': flat_pace_min_per_km,
        },
    }

    # Save prediction to database
    db_prediction = Prediction(
        user_id=user.id,
        gpx_file_id=gpx_file.id,
        flat_pace=flat_pace_min_per_km,
        user_fingerprint={'physics_params': user_params},
        total_time_seconds=total_time_sec,
        predicted_segments=ml_segments,
    )
    prediction_repo.create(db_prediction)
    prediction_repo.commit()

    return jsonify({
        'prediction_id': db_prediction.id,
        'prediction': prediction,
        'similar_activities': [],
    })

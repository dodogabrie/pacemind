"""Prediction API endpoints.

Workflow:
1. GET /api/prediction/calibration-activities - List user's activities for calibration
2. POST /api/prediction/calibrate - Compute flat_pace from selected activity
3. POST /api/prediction/predict - Generate route time prediction
"""

import io

import gpxpy
import gpxpy.gpx
from flask import Blueprint, request, jsonify, current_app, send_file
from datetime import datetime, timedelta, timezone
from cryptography.fernet import InvalidToken
import requests

from api.utils import get_current_user
from repositories import (
    UserRepository, ActivityRepository, GPXFileRepository, PredictionRepository
)
from services.strava_service import StravaService, StravaNotConnected
from services.cache_service import CacheService
from utils.constants import (
    LONG_ROUTE_THRESHOLD_M,
    ULTRA_ROUTE_THRESHOLD_M,
    LONG_RUN_THRESHOLD_M,
    SHORT_WORKOUT_THRESHOLD_M,
    ULTRA_RUN_THRESHOLD_M,
    DISTANCE_WEIGHT,
    ELEVATION_WEIGHT,
    EFFORT_WEIGHT,
    SIMILARITY_RECOMMENDATION_THRESHOLD,
)

bp = Blueprint('prediction', __name__, url_prefix='/api/prediction')

user_repo = UserRepository()
activity_repo = ActivityRepository()
gpx_repo = GPXFileRepository()
prediction_repo = PredictionRepository()


def get_cache_service() -> CacheService:
    """Get or create cache service via Flask app context (thread-safe)."""
    if 'cache_service' not in current_app.extensions:
        current_app.extensions['cache_service'] = CacheService()
    return current_app.extensions['cache_service']


def get_strava_service() -> StravaService:
    """Get Strava service instance."""
    return StravaService(
        current_app.config['STRAVA_CLIENT_ID'],
        current_app.config['STRAVA_CLIENT_SECRET'],
        current_app.config['STRAVA_REDIRECT_URI']
    )


def _parse_strava_datetime(value: str) -> datetime:
    """Parse Strava ISO datetimes (typically ending in 'Z')."""
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _select_fingerprint_activity_ids(
    *,
    calibration_activity_id: int,
    activities: list,
    months: int = 3,
    max_longest_runs: int = 10,
) -> list:
    """Select activities for user fingerprint extraction.

    Includes the calibration activity plus the longest runs from the last ~N months.
    Returns unique Strava activity IDs in priority order.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(months * 30))
    recent_runs = []
    for a in activities or []:
        if a.get('type') != 'Run':
            continue
        try:
            start_date = _parse_strava_datetime(a.get('start_date'))
        except Exception:
            continue
        if start_date < cutoff:
            continue
        dist = a.get('distance') or 0
        if dist <= 0:
            continue
        recent_runs.append(a)

    recent_runs.sort(key=lambda x: x.get('distance', 0), reverse=True)

    selected = [int(calibration_activity_id)]
    for run in recent_runs[:max_longest_runs]:
        rid = run.get('id')
        if rid is None:
            continue
        rid = int(rid)
        if rid not in selected:
            selected.append(rid)

    return selected


# ---------------------------------------------------------------------------
# Similarity scoring (extracted from get_calibration_activities)
# ---------------------------------------------------------------------------

def _compute_similarity_score(
    act_distance: float,
    act_elevation: float,
    target_distance: float,
    target_elevation: float | None,
) -> tuple[float, bool]:
    """Compute similarity score (0-1) and recommendation flag for an activity.

    Returns:
        (similarity_score, recommended)
    """
    # Distance similarity (0-1)
    dist_diff_pct = abs(act_distance - target_distance) / max(target_distance, 1)
    distance_sim = max(0, 1 - dist_diff_pct)

    # Elevation similarity (0-1)
    elevation_sim = 0.5  # Neutral if no elevation data
    if target_elevation and target_elevation > 100:
        elev_diff_pct = abs(act_elevation - target_elevation) / max(target_elevation, 1)
        elevation_sim = max(0, 1 - elev_diff_pct)

    # Effort type bonus — prioritize similar-length runs
    effort_bonus = 0.5
    if target_distance > ULTRA_ROUTE_THRESHOLD_M:
        if act_distance > ULTRA_RUN_THRESHOLD_M:
            effort_bonus = 1.0
        elif act_distance < LONG_ROUTE_THRESHOLD_M:
            effort_bonus = 0.1
    elif target_distance > LONG_ROUTE_THRESHOLD_M:
        if act_distance > LONG_RUN_THRESHOLD_M:
            effort_bonus = 1.0
        elif act_distance < SHORT_WORKOUT_THRESHOLD_M:
            effort_bonus = 0.2

    score = (
        distance_sim * DISTANCE_WEIGHT
        + elevation_sim * ELEVATION_WEIGHT
        + effort_bonus * EFFORT_WEIGHT
    )
    recommended = score > SIMILARITY_RECOMMENDATION_THRESHOLD
    return score, recommended


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# TODO(multi-source #88 — see GH issues): Strava-only list; file-import users get [].
# Imported activities live in the `activities` table but aren't offered here, and
# save-calibration selects by strava_id. Fix: a source-agnostic GET /api/activities.
@bp.route('/calibration-activities', methods=['GET'])
def get_calibration_activities():
    """Get user's Strava activities suitable for calibration.

    Query params:
        - gpx_id (optional): If provided, filter to similar distances
        - limit (optional): Max activities to return (default 50)
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        cache = get_cache_service()

        # Try cached activities first
        cached_activities = cache.get_cached_activities(user.id, max_age_hours=24)

        if cached_activities:
            current_app.logger.debug(f"Using cached activities for user {user.id}")
            activities = cached_activities
        else:
            current_app.logger.debug(f"No cache, fetching from Strava for user {user.id}")
            service = get_strava_service()

            access_token, refresh_token, expires_at = service.get_valid_token(
                user.access_token, user.refresh_token, user.expires_at
            )
            if access_token != user.access_token:
                user.access_token = access_token
                user.refresh_token = refresh_token
                user.expires_at = expires_at
                user_repo.commit()

            after = service.get_timestamp_for_last_year()
            activities = service.fetch_activities(access_token, after)
            cache.cache_activities(user.id, activities, after_timestamp=after)

        # Filter to runs only
        activities = [a for a in activities if a.get('type') == 'Run']

        # Get GPX route info for similarity scoring
        gpx_id = request.args.get('gpx_id', type=int)
        target_distance = None
        target_elevation = None
        if gpx_id:
            gpx_file = gpx_repo.get_user_file(gpx_id, user.id)
            if gpx_file and gpx_file.data:
                target_distance = gpx_file.data.get('total_distance')
                target_elevation = gpx_file.data.get('total_ascent', 0)

        formatted = []
        for activity in activities:
            cached = activity_repo.get_by_strava_id(user.id, activity['id'])

            similarity_score = 0.0
            recommended = False
            if target_distance:
                similarity_score, recommended = _compute_similarity_score(
                    activity['distance'],
                    activity.get('total_elevation_gain', 0),
                    target_distance,
                    target_elevation,
                )

            formatted.append({
                'strava_id': activity['id'],
                'name': activity['name'],
                'distance': activity['distance'],
                'distance_km': round(activity['distance'] / 1000, 2),
                'elevation_gain': activity.get('total_elevation_gain', 0),
                'start_date': activity['start_date'],
                'has_streams': cached is not None and cached.streams is not None,
                'recommended': recommended,
                'similarity_score': round(similarity_score, 3),
                'moving_time': activity.get('moving_time'),
                'elapsed_time': activity.get('elapsed_time'),
            })

        formatted.sort(key=lambda x: (x['similarity_score'], x['start_date']), reverse=True)

        limit = request.args.get('limit', 50, type=int)
        formatted = formatted[:limit]

        return jsonify({
            'activities': formatted,
            'total': len(formatted),
        })

    except StravaNotConnected:
        return jsonify({'activities': [], 'total': 0, 'strava_connected': False})
    except InvalidToken:
        return jsonify({'error': 'Strava tokens are invalid (cannot decrypt). Please reconnect Strava.'}), 401
    except Exception as e:
        current_app.logger.error(f"Fetch calibration activities error: {str(e)}")
        return jsonify({'error': 'Failed to fetch activities'}), 500


@bp.route('/save-calibration', methods=['POST'])
def save_calibration():
    """Save user-edited calibration to profile."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    flat_pace = data.get('flat_pace_min_per_km')
    anchor_ratios = data.get('anchor_ratios')

    if not flat_pace or flat_pace <= 0 or flat_pace > 20:
        return jsonify({'error': 'Invalid flat_pace (must be 0-20 min/km)'}), 400

    if not anchor_ratios or len(anchor_ratios) < 3:
        return jsonify({'error': 'Need at least 3 anchor ratios'}), 400

    for grade, ratio in anchor_ratios.items():
        if ratio < 0.3 or ratio > 6.0:
            return jsonify({'error': f'Invalid ratio {ratio} at grade {grade} (must be 0.3-6.0)'}), 400

    try:
        user.saved_flat_pace = float(flat_pace)
        user.saved_anchor_ratios = {str(k): float(v) for k, v in anchor_ratios.items()}
        user.calibration_updated_at = datetime.now(timezone.utc)
        user.calibration_activity_id = data.get('calibration_activity_id')
        user_repo.commit()

        return jsonify({
            'message': 'Calibration saved',
            'user': {
                'saved_flat_pace': user.saved_flat_pace,
                'calibration_updated_at': user.calibration_updated_at.isoformat() if user.calibration_updated_at else None,
                'calibration_activity_id': user.calibration_activity_id,
            },
        })

    except Exception as e:
        current_app.logger.error(f"Save calibration error: {str(e)}")
        user_repo.rollback()
        return jsonify({'error': 'Failed to save calibration'}), 500


@bp.route('/<int:prediction_id>/export', methods=['GET'])
def export_prediction_gpx(prediction_id):
    """Export prediction as GPX with timestamps (Virtual Partner)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    prediction = prediction_repo.get_user_prediction(prediction_id, user.id)
    if not prediction:
        return jsonify({'error': 'Prediction not found'}), 404

    gpx_db_file = prediction.gpx_file
    if not gpx_db_file or not gpx_db_file.data:
        return jsonify({'error': 'Original GPX data missing'}), 404

    try:
        points = gpx_db_file.data['points']
        segments = prediction.predicted_segments

        new_gpx = gpxpy.gpx.GPX()

        # Add annotations as waypoints
        annotations = prediction.annotations or {'annotations': []}
        for ann in annotations.get('annotations', []):
            waypoint = gpxpy.gpx.GPXWaypoint(
                latitude=ann['lat'],
                longitude=ann['lon'],
                name=ann['label'],
            )
            waypoint.description = ann.get('description', '')

            type_map = {
                'aid_station': 'WATER',
                'water': 'WATER',
                'checkpoint': 'FLAG',
                'caution': 'DANGER',
                'generic': 'GENERIC',
            }
            symbol = type_map.get(ann['type'], 'GENERIC')
            waypoint.symbol = symbol
            waypoint.type = symbol
            new_gpx.waypoints.append(waypoint)

        # Create track
        gpx_track = gpxpy.gpx.GPXTrack()
        new_gpx.tracks.append(gpx_track)
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        gpx_track.segments.append(gpx_segment)

        start_time = datetime(2025, 1, 1, 8, 0, 0)

        # Pre-calculate cumulative time at each segment boundary
        cum_time_at_seg_start = [0.0]
        for s in segments:
            seg_time = s.get('time_s') or s.get('time_seconds', 0)
            cum_time_at_seg_start.append(cum_time_at_seg_start[-1] + seg_time)

        # Interpolate time for each point
        seg_idx = 0
        for p in points:
            dist_km = p['distance'] / 1000.0

            while seg_idx < len(segments) - 1 and dist_km > segments[seg_idx]['end_km']:
                seg_idx += 1

            seg = segments[seg_idx]
            seg_start_km = seg['start_km']
            seg_end_km = seg['end_km']
            seg_duration = seg.get('time_s') or seg.get('time_seconds', 0)
            seg_start_time = cum_time_at_seg_start[seg_idx]

            if seg_end_km > seg_start_km:
                fraction = (dist_km - seg_start_km) / (seg_end_km - seg_start_km)
                fraction = max(0, min(1, fraction))
                point_time_sec = seg_start_time + (fraction * seg_duration)
            else:
                point_time_sec = seg_start_time

            dt = start_time + timedelta(seconds=point_time_sec)
            new_point = gpxpy.gpx.GPXTrackPoint(
                latitude=p['lat'],
                longitude=p['lon'],
                elevation=p['elevation'],
                time=dt,
            )
            gpx_segment.points.append(new_point)

        xml = new_gpx.to_xml()

        mem_file = io.BytesIO()
        mem_file.write(xml.encode('utf-8'))
        mem_file.seek(0)

        filename = f"predicted_{gpx_db_file.original_filename}"
        return send_file(
            mem_file,
            as_attachment=True,
            download_name=filename,
            mimetype='application/gpx+xml',
        )

    except Exception as e:
        current_app.logger.error(f"Export error: {str(e)}")
        logger = current_app.logger
        logger.exception("Export failed")
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@bp.route('/<int:prediction_id>/annotations', methods=['PUT'])
def update_annotations(prediction_id):
    """Update annotations for a prediction."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    prediction = prediction_repo.get_user_prediction(prediction_id, user.id)
    if not prediction:
        return jsonify({'error': 'Prediction not found'}), 404

    data = request.get_json()
    annotations = data.get('annotations', [])

    for ann in annotations:
        required = ['id', 'type', 'distance_km', 'lat', 'lon', 'label']
        if not all(k in ann for k in required):
            return jsonify({'error': 'Invalid annotation structure - missing required fields'}), 400
        if ann['type'] not in ('aid_station', 'generic', 'water', 'checkpoint', 'caution'):
            return jsonify({'error': 'Invalid annotation type'}), 400

    prediction.annotations = {'annotations': annotations}
    prediction_repo.commit()

    return jsonify({'success': True, 'annotations': annotations})


@bp.route('/<int:prediction_id>/annotations', methods=['GET'])
def get_annotations(prediction_id):
    """Get annotations for a prediction."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    prediction = prediction_repo.get_user_prediction(prediction_id, user.id)
    if not prediction:
        return jsonify({'error': 'Prediction not found'}), 404

    annotations = prediction.annotations or {'annotations': []}
    return jsonify(annotations)

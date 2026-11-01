"""Annotation and waypoint handlers."""

import uuid
from typing import Dict, Any
from datetime import datetime, timezone

from config.hybrid_config import get_logger
from repositories import PredictionRepository
from services.agent.tool_handlers.validation import (
    _get_gpx_points, _resolve_lat_lon,
    VALID_WAYPOINT_TYPES, DEFAULT_STOP_TIMES,
)

logger = get_logger(__name__)


def _handle_suggest_waypoints(tool_input: Dict, user_id: int) -> Dict:
    """Propose waypoints for user review."""
    gpx_id = tool_input.get('gpx_id')
    waypoints = tool_input.get('waypoints', [])

    if not gpx_id:
        return {'error': 'gpx_id is required'}
    if not waypoints:
        return {'error': 'waypoints list is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    total_distance_m = points[-1].get('distance', 0) if points else 0
    total_distance_km = total_distance_m / 1000

    enriched = []
    for wp in waypoints:
        dist_km = wp.get('distance_km', 0)
        wp_type = wp.get('type', 'generic')
        label = wp.get('label', '')

        if wp_type not in VALID_WAYPOINT_TYPES:
            continue
        if dist_km < 0 or dist_km > total_distance_km + 0.1:
            continue

        lat_lon = _resolve_lat_lon(points, dist_km)
        if not lat_lon:
            continue

        stop_time = wp.get('stop_time_seconds')
        if stop_time is None:
            stop_time = DEFAULT_STOP_TIMES.get(wp_type, 0)

        enriched.append({
            'id': str(uuid.uuid4()),
            'distance_km': round(dist_km, 2),
            'type': wp_type,
            'label': label,
            'stop_time_seconds': stop_time,
            'reason': wp.get('reason', ''),
            'lat': lat_lon[0],
            'lon': lat_lon[1],
        })

    return {
        'suggested_annotations': enriched,
        'gpx_id': gpx_id,
        'total_distance_km': round(total_distance_km, 2),
        'count': len(enriched),
    }


def _handle_manage_annotations(tool_input: Dict, user_id: int) -> Dict:
    """Direct CRUD on prediction annotations."""
    prediction_id = tool_input.get('prediction_id')
    action = tool_input.get('action')

    if not prediction_id:
        return {'error': 'prediction_id is required'}
    if action not in ('add', 'remove', 'update', 'list'):
        return {'error': f'Invalid action: {action}'}

    prediction_repo = PredictionRepository()
    prediction = prediction_repo.get_user_prediction(prediction_id, user_id)
    if not prediction:
        return {'error': f'Prediction {prediction_id} not found'}

    annotations_data = prediction.annotations or {'annotations': []}
    annotations = annotations_data.get('annotations', [])

    if action == 'list':
        return {
            'annotations': annotations,
            'count': len(annotations),
            'action': 'list',
            'success': True,
        }

    if action == 'add':
        ann_input = tool_input.get('annotation', {})
        if not ann_input:
            return {'error': 'annotation data is required for add action'}

        ann_type = ann_input.get('type', 'generic')
        if ann_type not in VALID_WAYPOINT_TYPES:
            return {'error': f'Invalid annotation type: {ann_type}'}

        dist_km = ann_input.get('distance_km', 0)

        # Resolve lat/lon from GPX
        gpx_file = prediction.gpx_file
        if gpx_file and gpx_file.data:
            points = gpx_file.data.get('points', [])
            lat_lon = _resolve_lat_lon(points, dist_km)
        else:
            lat_lon = None

        stop_time = ann_input.get('stop_time_seconds')
        if stop_time is None:
            stop_time = DEFAULT_STOP_TIMES.get(ann_type, 0)

        new_ann = {
            'id': str(uuid.uuid4()),
            'type': ann_type,
            'distance_km': round(dist_km, 2),
            'label': ann_input.get('label', ann_type),
            'stop_time_seconds': stop_time,
            'lat': lat_lon[0] if lat_lon else 0,
            'lon': lat_lon[1] if lat_lon else 0,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        annotations.append(new_ann)

    elif action == 'remove':
        ann_id = tool_input.get('annotation_id')
        if not ann_id:
            return {'error': 'annotation_id is required for remove action'}
        original_len = len(annotations)
        annotations = [a for a in annotations if a.get('id') != ann_id]
        if len(annotations) == original_len:
            return {'error': f'Annotation {ann_id} not found'}

    elif action == 'update':
        ann_id = tool_input.get('annotation_id')
        ann_input = tool_input.get('annotation', {})
        if not ann_id:
            return {'error': 'annotation_id is required for update action'}

        found = False
        for ann in annotations:
            if ann.get('id') == ann_id:
                if 'label' in ann_input:
                    ann['label'] = ann_input['label']
                if 'stop_time_seconds' in ann_input:
                    ann['stop_time_seconds'] = ann_input['stop_time_seconds']
                if 'type' in ann_input and ann_input['type'] in VALID_WAYPOINT_TYPES:
                    ann['type'] = ann_input['type']
                found = True
                break
        if not found:
            return {'error': f'Annotation {ann_id} not found'}

    from sqlalchemy.orm.attributes import flag_modified
    prediction.annotations = {'annotations': annotations}
    flag_modified(prediction, 'annotations')
    prediction_repo.commit()

    return {
        '_annotations_updated': True,
        'annotations': annotations,
        'count': len(annotations),
        'action': action,
        'success': True,
    }

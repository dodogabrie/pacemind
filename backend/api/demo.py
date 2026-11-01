"""Anonymous demo prediction — no auth, no Strava, physics-only.

Lets first-time visitors run the prediction pipeline on a bundled sample
race GPX so they can see the product before connecting Strava. Tier is
forced to physics (no per-user calibration); IPs are throttled in-memory.
"""

import hashlib
import os
import time
from collections import deque
from pathlib import Path
from threading import Lock

from flask import Blueprint, current_app, jsonify, request

from api.hybrid import _extract_flat_pace, _format_segments
from services.data_processor import process_gpx_data
from services.gpx_parser import parse_gpx_file
from services.hybrid_prediction_service import HybridPredictionService
from utils.formatting import format_seconds_to_hms_padded

bp = Blueprint('demo', __name__, url_prefix='/api/demo')

# Whitelisted demo routes — extend with new sample GPX files here.
DEMO_ROUTES = {
    'utmb_pyramides': {
        'filename': 'utmb-sample.gpx',
        'display_name': 'UTMB Pyramides (sample)',
    },
}

# Simple in-memory rate limiter: 10 req / hour / IP-hash.
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW_SEC = 3600
_rate_buckets: dict[str, deque] = {}
_rate_lock = Lock()


def _ip_hash() -> str:
    ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '') or '').split(',')[0].strip()
    salt = current_app.config.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY', '')
    return hashlib.sha256(f"{ip}:{salt}".encode('utf-8')).hexdigest()[:32]


def _rate_limited(key: str) -> bool:
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SEC
    with _rate_lock:
        bucket = _rate_buckets.setdefault(key, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX:
            return True
        bucket.append(now)
        return False


def _demo_data_dir() -> Path:
    """Resolve backend/data/demo relative to the running app."""
    return Path(current_app.root_path) / 'data' / 'demo'


@bp.route('/routes', methods=['GET'])
def list_demo_routes():
    """List available demo routes."""
    return jsonify({
        'routes': [
            {'id': key, 'display_name': meta['display_name']}
            for key, meta in DEMO_ROUTES.items()
        ]
    })


@bp.route('/predict', methods=['POST'])
def predict_demo():
    """Anonymous physics prediction on a bundled sample GPX."""
    data = request.get_json(silent=True) or {}
    route_id = data.get('route_id') or 'utmb_pyramides'

    meta = DEMO_ROUTES.get(route_id)
    if not meta:
        return jsonify({'error': 'Unknown demo route'}), 400

    if _rate_limited(_ip_hash()):
        return jsonify({
            'error': 'Demo rate limit reached',
            'message': 'Try again in an hour, or sign in to run unlimited predictions.',
        }), 429

    gpx_path = _demo_data_dir() / meta['filename']
    if not gpx_path.exists():
        current_app.logger.error(f"Demo GPX missing on disk: {gpx_path}")
        return jsonify({'error': 'Demo route not available'}), 503

    try:
        parsed = parse_gpx_file(gpx_path)
        processed = process_gpx_data(parsed)
        points = processed.get('points', [])
        if not points:
            return jsonify({'error': 'Demo GPX has no points'}), 500

        result = HybridPredictionService().predict(
            user_id=None,
            gpx_points=points,
            force_tier='physics',
            include_diagnostics=False,
            effort='training',
        )

        if 'error' in result:
            return jsonify(result), 500

        metadata = result.get('metadata', {})
        segments = result.get('segments', [])
        formatted_segments = _format_segments(segments)
        total_time_sec = float(result['total_time_seconds'])

        total_elevation_gain = sum(
            seg.get('length_m', 0) * seg.get('grade', 0)
            for seg in segments
            if seg.get('grade', 0) > 0
        )

        return jsonify({
            'route': {
                'id': route_id,
                'display_name': meta['display_name'],
                'bounds': processed.get('bounds'),
                'points': points,
                'total_distance': processed.get('total_distance'),
            },
            'prediction': {
                'total_time_seconds': total_time_sec,
                'total_time_formatted': format_seconds_to_hms_padded(total_time_sec),
                'confidence_interval': result['confidence_interval'],
                'segments': formatted_segments,
                'statistics': {
                    'total_distance_km': formatted_segments[-1]['end_km'] if formatted_segments else 0,
                    'total_elevation_gain_m': total_elevation_gain,
                    'flat_pace_min_per_km': _extract_flat_pace(result),
                },
                'metadata': metadata,
            },
        })

    except Exception as e:
        current_app.logger.exception(f"Demo prediction error: {e}")
        return jsonify({'error': 'Demo prediction failed'}), 500

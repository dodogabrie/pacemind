"""Weather API endpoints for the course planning widget.

Provides forecast data with sunrise/sunset, forecast accuracy,
and recent weather history for terrain condition assessment.
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify
from api.utils import get_current_user
from api.billing import requires_premium
from repositories import GPXFileRepository
from services.weather_service import WeatherService

logger = logging.getLogger(__name__)

weather_bp = Blueprint('weather', __name__, url_prefix='/api/weather')

gpx_repo = GPXFileRepository()


@weather_bp.route('/forecast', methods=['GET'])
@requires_premium('weather_forecast')
def get_weather_forecast():
    """Get weather forecast for a GPX route on a specific date.

    Query params:
        gpx_id: ID of the GPX route (required)
        date: Target date YYYY-MM-DD (optional, defaults to today)

    Returns:
        JSON with forecast, accuracy, recent_weather, conditions_description
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    gpx_id = request.args.get('gpx_id', type=int)
    if not gpx_id:
        return jsonify({'error': 'gpx_id is required'}), 400

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)
    if not gpx_file or not gpx_file.data:
        return jsonify({'error': 'GPX route not found'}), 404

    points = gpx_file.data.get('points', [])
    if not points:
        return jsonify({'error': 'GPX route has no points'}), 400

    # Compute route centroid
    lats = [p['lat'] for p in points if 'lat' in p]
    lons = [p['lon'] for p in points if 'lon' in p]
    if not lats or not lons:
        return jsonify({'error': 'GPX route has no valid coordinates'}), 400

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    # Parse and validate date
    date_str = request.args.get('date')
    today = datetime.now(timezone.utc).date()
    max_date = today + timedelta(days=16)

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

        if target_date.date() < today:
            return jsonify({'error': 'Date cannot be in the past'}), 400
        if target_date.date() > max_date:
            return jsonify({'error': 'Forecast available up to 16 days ahead'}), 400
    else:
        target_date = datetime.now(timezone.utc)

    service = WeatherService()
    try:
        data = service.get_weather_widget_data(center_lat, center_lon, target_date)
    except Exception as e:
        logger.error(f"Weather service error: {e}")
        return jsonify({'error': 'Weather service unavailable'}), 502

    if not data:
        return jsonify({'error': 'Failed to fetch weather data'}), 502

    return jsonify(data)

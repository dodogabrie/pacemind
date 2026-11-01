"""Race brief data builder.

Produces the structured dict consumed by both:
- the agent tool `get_race_briefing` (returns JSON to Claude)
- the PDF endpoint `/api/agent/race-brief.pdf` (renders to PDF)

Keeping a single source of truth means the prose Claude sees and the
artifact the user downloads describe the same numbers.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from config.hybrid_config import get_logger
from services.hybrid_prediction_service import HybridPredictionService
from services.osm_terrain_service import OSMTerrainService
from services.weather_service import WeatherService
from services.training_load_service import TrainingLoadService
from services.agent.tool_handlers.validation import _get_gpx_points

logger = get_logger(__name__)


def build_race_brief(
    user_id: int,
    gpx_id: int,
    race_date_str: Optional[str] = None,
    effort: str = 'race',
) -> Dict:
    """Build the structured race-brief dict.

    Returns the same shape `_handle_get_race_briefing` used to return inline.
    On hard error returns `{'error': '...'}`.
    """
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    race_date = (
        datetime.strptime(race_date_str, "%Y-%m-%d")
        if race_date_str
        else datetime.now(timezone.utc)
    )

    # TODO(pred-review #30 — see GH issues): terrain + weather below are shown
    # but not fed to the prediction. Wire them only as factors relative to the
    # user's calibration runs (v_flat already reflects their usual terrain).
    # 1. Terrain
    terrain_service = OSMTerrainService()
    terrain_factors = terrain_service.get_terrain_for_route(points, bounds)
    terrain_summary = terrain_service.get_terrain_summary(terrain_factors)
    terrain_desc = terrain_service.describe_terrain(terrain_summary)

    # 2. Weather
    weather_service = WeatherService()
    weather = weather_service.get_weather_for_route(points, race_date, is_historical=False)
    weather_desc = weather_service.describe_conditions(weather) if weather else "Weather data unavailable"
    weather_factor = weather.get('weather_factor', 1.0) if weather else 1.0

    # 3. Training load
    training_service = TrainingLoadService()
    training_load = training_service.get_training_load(user_id)

    # 4. Prediction
    prediction_service = HybridPredictionService()
    result = prediction_service.predict(
        user_id=user_id,
        gpx_points=points,
        include_diagnostics=False,
        effort=effort,
    )

    total_time = result.get('total_time_seconds', 0)
    h = int(total_time // 3600)
    m = int((total_time % 3600) // 60)
    s = int(total_time % 60)

    segments = result.get('segments', [])
    total_distance_km = (
        (segments[-1]['distance_m'] + segments[-1]['length_m']) / 1000 if segments else 0
    )
    total_elevation = sum(
        seg.get('length_m', 0) * seg.get('grade', 0)
        for seg in segments if seg.get('grade', 0) > 0
    )

    key_challenges = []
    for seg in segments:
        grade_pct = seg.get('grade', 0) * 100
        dist_km = seg.get('distance_m', 0) / 1000
        if grade_pct > 15:
            key_challenges.append(f"Steep climb ({grade_pct:.0f}%) at km {dist_km:.1f}")
        elif grade_pct < -15:
            key_challenges.append(f"Steep descent ({abs(grade_pct):.0f}%) at km {dist_km:.1f}")
    key_challenges = key_challenges[:5]

    return {
        'route': {
            'distance_km': round(total_distance_km, 2),
            'elevation_gain_m': round(total_elevation, 0),
        },
        'terrain': {
            'summary': terrain_summary.get('category_breakdown', {}),
            'description': terrain_desc,
        },
        'weather': {
            'conditions': weather,
            'description': weather_desc,
            'weather_factor': round(weather_factor, 3),
        },
        'training_status': {
            'form': training_load.get('form', 'unknown'),
            'tsb': training_load.get('tsb', 0),
            'interpretation': training_load.get('interpretation', ''),
        },
        'prediction': {
            'total_time_formatted': f"{h}:{m:02d}:{s:02d}",
            'total_time_seconds': total_time,
            'effort': effort,
            'confidence_interval': result.get('confidence_interval'),
            'tier': result.get('metadata', {}).get('tier', 'unknown'),
        },
        'key_challenges': key_challenges,
        'gpx_id': gpx_id,
        'race_date': race_date.strftime("%Y-%m-%d"),
    }

"""Equipment suggestion handler."""

from typing import Dict, Any
from datetime import datetime, timezone

from config.hybrid_config import get_logger
from services.hybrid_prediction_service import HybridPredictionService
from services.weather_service import WeatherService
from services.osm_terrain_service import OSMTerrainService
from services.agent.tool_handlers.validation import _get_gpx_points

logger = get_logger(__name__)


def _handle_get_equipment_suggestion(tool_input: Dict, user_id: int) -> Dict:
    """Suggest gear and equipment based on weather, terrain, and expected duration."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    # Parse date
    date_str = tool_input.get('date')
    date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now(timezone.utc)

    # Get weather data (forecast + recent)
    weather_service = WeatherService()
    lats = [p['lat'] for p in points if 'lat' in p]
    lons = [p['lon'] for p in points if 'lon' in p]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    forecast = weather_service.get_forecast_with_sun(center_lat, center_lon, date)
    recent = weather_service.get_recent_weather_summary(center_lat, center_lon)

    # Get terrain data
    terrain_service = OSMTerrainService()
    terrain_factors = terrain_service.get_terrain_for_route(points, bounds)
    terrain_summary = terrain_service.get_terrain_summary(terrain_factors)

    # Get predicted duration estimate
    estimated_hours = None
    try:
        prediction_service = HybridPredictionService()
        result = prediction_service.predict(user_id, points, effort='training')
        if result and result.get('total_time_seconds'):
            estimated_hours = result['total_time_seconds'] / 3600
    except Exception as e:
        logger.warning(f"Could not get duration estimate for equipment: {e}")

    # Build recommendations
    recommendations = {}
    temp = forecast.get('temperature_c', 15) if forecast else 15
    wind = forecast.get('wind_speed_ms', 0) if forecast else 0
    precip = forecast.get('precipitation_mm', 0) if forecast else 0
    humidity = forecast.get('humidity_pct', 50) if forecast else 50
    daylight_hours = forecast.get('daylight_hours') if forecast else None
    weathercode = forecast.get('weathercode') if forecast else None
    recent_precip = recent.get('total_precipitation_mm', 0) if recent else 0
    terrain_impact = recent.get('terrain_impact', '') if recent else ''

    # Surface breakdown from terrain
    surface_pcts = terrain_summary.get('surface_breakdown', {}) if terrain_summary else {}
    paved_pct = surface_pcts.get('asphalt', 0) + surface_pcts.get('concrete', 0)
    technical_pct = surface_pcts.get('rock', 0) + surface_pcts.get('roots', 0)
    mud_pct = surface_pcts.get('mud', 0)

    # --- Shoes ---
    if paved_pct > 50:
        shoes = "Road running shoes — route is mostly paved"
    elif recent_precip >= 15 or mud_pct > 10:
        shoes = "Waterproof trail shoes with aggressive lugs — recent rain means muddy, slippery trails"
    elif technical_pct > 20:
        shoes = "Trail shoes with aggressive lugs — route has significant technical terrain (rocks/roots)"
    elif recent_precip >= 5:
        shoes = "Trail shoes with good grip — trails may be damp from recent precipitation"
    else:
        shoes = "Light trail shoes — dry conditions expected"
    recommendations['shoes'] = shoes

    # --- Clothing ---
    if temp < 0:
        clothing = "Thermal base layer, insulated jacket, running tights, gloves, buff/beanie — freezing conditions"
    elif temp < 10:
        clothing = "Long sleeve base layer, light jacket, running tights or shorts with leg warmers"
    elif temp < 18:
        clothing = "Short sleeve or light long sleeve, arm warmers optional"
    elif temp < 25:
        clothing = "Light singlet or t-shirt, shorts"
    else:
        clothing = "Ultralight singlet, shorts — consider cooling accessories (wet bandana, ice)"
    recommendations['clothing'] = clothing

    # --- Rain gear ---
    if precip >= 5:
        recommendations['rain_gear'] = "Waterproof jacket required — significant precipitation expected"
    elif precip >= 0.5:
        recommendations['rain_gear'] = "Packable rain jacket — light precipitation possible"
    else:
        recommendations['rain_gear'] = "Not needed — dry conditions forecast"

    # --- Headlamp ---
    if estimated_hours and daylight_hours:
        if estimated_hours > daylight_hours:
            recommendations['headlamp'] = (
                f"Required — estimated duration ({estimated_hours:.1f}h) exceeds "
                f"daylight hours ({daylight_hours:.1f}h)"
            )
        elif estimated_hours > daylight_hours * 0.8:
            recommendations['headlamp'] = (
                f"Recommended as backup — estimated duration ({estimated_hours:.1f}h) is close to "
                f"daylight hours ({daylight_hours:.1f}h)"
            )
        else:
            recommendations['headlamp'] = "Not needed if starting during daylight"
    elif daylight_hours and daylight_hours < 10:
        recommendations['headlamp'] = "Recommended — short daylight window"
    else:
        recommendations['headlamp'] = "Carry as backup for longer efforts"

    # --- Hydration ---
    base_rate = 500  # ml/h
    if temp > 25:
        base_rate = 750
    elif temp <= 10:
        base_rate = 400
    if humidity > 70:
        base_rate += 100

    if estimated_hours:
        total_fluid = int(base_rate * estimated_hours)
        if total_fluid > 1500:
            hydration = (
                f"~{base_rate} ml/hour ({total_fluid} ml total). "
                f"Use a hydration vest (1.5-2L capacity)"
            )
        else:
            hydration = (
                f"~{base_rate} ml/hour ({total_fluid} ml total). "
                f"Handheld flask or belt sufficient"
            )
    else:
        hydration = f"~{base_rate} ml/hour recommended"
    recommendations['hydration'] = hydration

    # --- Sun protection ---
    if weathercode is not None and weathercode <= 2 and temp > 15:
        recommendations['sun_protection'] = "Sunscreen SPF 30+, cap/visor, sunglasses — clear skies expected"
    elif temp > 20:
        recommendations['sun_protection'] = "Cap optional, sunscreen if exposed sections"
    else:
        recommendations['sun_protection'] = "Minimal needed"

    # --- Wind protection ---
    if wind > 8:
        recommendations['wind_protection'] = f"Windproof jacket or vest — strong wind ({wind:.0f} m/s) expected"
    elif wind > 5:
        recommendations['wind_protection'] = "Light windbreaker recommended for exposed sections"

    return {
        'gpx_id': gpx_id,
        'date': date.strftime("%Y-%m-%d"),
        'recommendations': recommendations,
        'conditions_summary': {
            'temperature_c': temp,
            'wind_speed_ms': wind,
            'precipitation_mm': precip,
            'humidity_pct': humidity,
            'daylight_hours': daylight_hours,
            'recent_precipitation_mm': recent_precip,
            'terrain_impact': terrain_impact,
            'estimated_duration_hours': round(estimated_hours, 1) if estimated_hours else None,
        },
    }

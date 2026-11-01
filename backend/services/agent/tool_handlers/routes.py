"""Route-related handlers: list, segments, terrain, weather, training routes."""

from typing import Dict, Any
from datetime import datetime, timezone

from config.hybrid_config import get_logger
from repositories import GPXFileRepository
from services.osm_terrain_service import OSMTerrainService
from services.weather_service import WeatherService
from services.agent.tool_handlers.validation import _get_gpx_points

logger = get_logger(__name__)


def _handle_list_gpx_routes(tool_input: Dict, user_id: int) -> Dict:
    """List user's uploaded GPX routes."""
    gpx_repo = GPXFileRepository()
    routes = gpx_repo.get_user_files(user_id)

    route_list = []
    for r in routes:
        data = r.data or {}
        points = data.get('points', [])

        # Calculate basic stats
        distance_km = 0
        elevation_gain = 0
        if points:
            last = points[-1]
            distance_km = last.get('distance', 0) / 1000
            for i in range(1, len(points)):
                elev_diff = points[i].get('elevation', 0) - points[i - 1].get('elevation', 0)
                if elev_diff > 0:
                    elevation_gain += elev_diff

        route_list.append({
            'id': r.id,
            'filename': r.filename,
            'distance_km': round(distance_km, 2),
            'elevation_gain_m': round(elevation_gain, 0),
            'n_points': len(points),
        })

    return {'routes': route_list, 'total': len(route_list)}


def _handle_get_terrain_analysis(tool_input: Dict, user_id: int) -> Dict:
    """Analyze terrain types along a GPX route using OSM data."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    service = OSMTerrainService()
    terrain_factors = service.get_terrain_for_route(points, bounds)
    summary = service.get_terrain_summary(terrain_factors)
    description = service.describe_terrain(summary)

    return {
        'summary': summary,
        'description': description,
        'gpx_id': gpx_id,
    }


def _handle_get_weather_conditions(tool_input: Dict, user_id: int) -> Dict:
    """Get weather conditions for a route on a specific date."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    date_str = tool_input.get('date')
    mode = tool_input.get('mode', 'forecast')

    date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now(timezone.utc)
    is_historical = mode == 'historical'

    service = WeatherService()
    weather = service.get_weather_for_route(points, date, is_historical)

    if not weather:
        return {'error': 'Failed to fetch weather data'}

    description = service.describe_conditions(weather)

    return {
        'weather': weather,
        'description': description,
        'mode': mode,
        'gpx_id': gpx_id,
    }


def _handle_get_route_segments(tool_input: Dict, user_id: int) -> Dict:
    """Get segment-level data for waypoint placement reasoning."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    # Summarize every ~500m
    summary = []
    cum_gain = 0
    cum_loss = 0
    last_summary_dist = 0
    segment_elevations = []

    for i, p in enumerate(points):
        dist_m = p.get('distance', 0)
        elev = p.get('elevation', 0)

        if i > 0:
            elev_diff = elev - points[i - 1].get('elevation', 0)
            if elev_diff > 0:
                cum_gain += elev_diff
            else:
                cum_loss += abs(elev_diff)
        segment_elevations.append(elev)

        if dist_m - last_summary_dist >= 500 or i == len(points) - 1:
            segment_dist = dist_m - last_summary_dist
            if segment_dist > 0 and len(segment_elevations) >= 2:
                grade = (segment_elevations[-1] - segment_elevations[0]) / segment_dist
            else:
                grade = 0

            summary.append({
                'distance_km': round(dist_m / 1000, 2),
                'elevation_m': round(elev, 0),
                'grade_pct': round(grade * 100, 1),
                'cum_gain_m': round(cum_gain, 0),
                'cum_loss_m': round(cum_loss, 0),
            })
            last_summary_dist = dist_m
            segment_elevations = [elev]

    total_distance_km = points[-1].get('distance', 0) / 1000 if points else 0

    return {
        'segments': summary,
        'total_distance_km': round(total_distance_km, 2),
        'total_elevation_gain_m': round(cum_gain, 0),
        'total_elevation_loss_m': round(cum_loss, 0),
        'n_segments': len(summary),
        'gpx_id': gpx_id,
    }


def _handle_search_training_routes(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Search user's saved training routes."""
    from repositories import TrainingRouteRepository
    repo = TrainingRouteRepository()

    routes = repo.search_by_criteria(
        user_id=user_id,
        min_distance_km=tool_input.get('min_distance_km'),
        max_distance_km=tool_input.get('max_distance_km'),
        min_elevation_m=tool_input.get('min_elevation_m'),
        max_elevation_m=tool_input.get('max_elevation_m'),
    )

    if not routes:
        return {'routes': [], 'message': 'No routes found matching criteria.'}

    return {
        'routes': [r.to_summary() for r in routes],
        'count': len(routes),
    }


def _handle_generate_training_route(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Generate a new training route via ORS."""
    from repositories import UserRepository
    from services.route_generation_service import RouteGenerationService
    from models.training_route import TrainingRoute
    from repositories import TrainingRouteRepository

    user_repo = UserRepository()
    user = user_repo.get_by_id(user_id)
    if not user:
        return {'error': 'User not found.'}

    # Get training base location
    lat = user.training_base_lat
    lon = user.training_base_lon

    if not lat or not lon:
        # Try to infer
        service = RouteGenerationService()
        inferred = service.infer_training_base(user_id)
        if inferred:
            lat = inferred['lat']
            lon = inferred['lon']
        else:
            return {'error': 'No training base location set. Ask the user to set their training location in the Routes page.'}

    service = RouteGenerationService()
    target_distance = tool_input.get('target_distance_km', 10)
    target_elevation = tool_input.get('target_elevation_m')

    result = service.generate_loop_route(
        center_lat=lat,
        center_lon=lon,
        target_distance_km=target_distance,
        target_elevation_m=target_elevation,
    )

    if 'error' in result:
        return result

    name = tool_input.get('name', f"Training loop {target_distance}km")

    route = TrainingRoute(
        user_id=user_id,
        name=name,
        source='generated',
        route_data=result['route_data'],
        distance_km=result['distance_km'],
        elevation_gain_m=result['elevation_gain_m'],
        elevation_loss_m=result['elevation_loss_m'],
        center_lat=round(lat, 6),
        center_lon=round(lon, 6),
        tags=[],
        generation_params={
            'center_lat': lat,
            'center_lon': lon,
            'target_distance_km': target_distance,
            'target_elevation_m': target_elevation,
        },
    )

    route_repo = TrainingRouteRepository()
    route_repo.create(route)
    route_repo.commit()

    return {
        'route': route.to_summary(),
        'message': f'Generated {result["distance_km"]}km route with {result["elevation_gain_m"]}m D+.',
    }


def _handle_build_route_workout(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Build segment-level workout steps for a route."""
    route_id = tool_input.get('route_id')
    if not route_id:
        return {'error': 'route_id is required.'}

    # Verify route belongs to user
    from repositories import TrainingRouteRepository
    repo = TrainingRouteRepository()
    route = repo.get_by_id(route_id)
    if not route or route.user_id != user_id:
        return {'error': 'Route not found.'}

    from services.workout_service import build_steps_from_route
    workout_type = tool_input.get('workout_type', 'long_run')
    focus = tool_input.get('focus', 'climbing')

    steps = build_steps_from_route(route_id, workout_type, focus)

    if not steps:
        return {'error': 'Could not build steps for this route.'}

    return {
        'route_id': route_id,
        'route_name': route.name,
        'workout_type': workout_type,
        'focus': focus,
        'steps': steps,
        'step_count': len(steps),
        'message': f'Built {len(steps)} steps for {route.name} ({route.distance_km}km, {route.elevation_gain_m}m D+).',
    }


def _handle_get_route_gpx_link(tool_input: Dict, user_id: int) -> Dict:
    """Return the authenticated GPX download path for a saved training route."""
    from repositories.training_route_repository import TrainingRouteRepository
    route = TrainingRouteRepository().get_user_route(tool_input.get('route_id'), user_id)
    if not route:
        return {'error': 'Route not found'}
    return {'route_id': route.id, 'name': route.name, 'download_path': f'/api/routes/{route.id}/gpx'}


def _handle_list_training_locations(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    from repositories import TrainingLocationRepository
    return {'locations': [l.to_dict() for l in TrainingLocationRepository().get_user_locations(user_id)]}


def _handle_set_training_location_for_day(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    from repositories import TrainingPlanRepository, UserTrainingPreferencesRepository
    from services.route_matcher import set_day_location
    repo = TrainingPlanRepository()
    plan = repo.get_user_plan(tool_input.get('plan_id'), user_id)
    if not plan:
        return {'error': 'Plan not found.'}
    try:
        day = set_day_location(plan, tool_input.get('week_number'), tool_input.get('day'),
                               tool_input.get('location_id'),
                               prefs=UserTrainingPreferencesRepository().get_by_user(user_id))
    except ValueError as e:
        return {'error': str(e)}
    if day is None:
        return {'error': 'Day not found in that week.'}
    repo.commit()
    return {'day': day.get('day'), 'location_id': day.get('location_id'),
            'resolved_location_id': day.get('resolved_location_id'),
            'route_id': day.get('route_id'), 'route_match_quality': day.get('route_match_quality')}

"""Training Routes API — browse, import from Strava, generate via ORS."""

import json
import re
import gpxpy
import gpxpy.gpx
from flask import Blueprint, request, jsonify, Response, stream_with_context
from api.utils import get_current_user
from repositories.training_route_repository import TrainingRouteRepository
from models.training_location import TrainingLocation
from repositories.training_location_repository import TrainingLocationRepository

bp = Blueprint('routes', __name__, url_prefix='/api/routes')
route_repo = TrainingRouteRepository()
location_repo = TrainingLocationRepository()


@bp.route('/', methods=['GET'])
def list_routes():
    """List user's training routes."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    routes = route_repo.get_user_routes(user.id)
    return jsonify({'routes': [r.to_summary() for r in routes]})


@bp.route('/<int:route_id>', methods=['GET'])
def get_route(route_id):
    """Get route details with segments."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    route = route_repo.get_user_route(route_id, user.id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404

    return jsonify(route.to_dict())


@bp.route('/<int:route_id>/gpx', methods=['GET'])
def download_gpx(route_id):
    """Download a saved route as a GPX file."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    route = route_repo.get_user_route(route_id, user.id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404

    g = gpxpy.gpx.GPX()
    trk = gpxpy.gpx.GPXTrack(name=route.name)
    seg = gpxpy.gpx.GPXTrackSegment()
    for p in route.route_data or []:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(p['lat'], p['lon'], elevation=p.get('elevation')))
    trk.segments.append(seg)
    g.tracks.append(trk)

    slug = re.sub(r'[^a-z0-9]+', '-', route.name.lower()).strip('-') or f'route-{route.id}'
    return Response(
        g.to_xml(), mimetype='application/gpx+xml',
        headers={'Content-Disposition': f'attachment; filename="{slug}.gpx"'},
    )


@bp.route('/from-strava/<int:activity_id>', methods=['POST'])
def import_from_strava(activity_id):
    """Import a route from a Strava activity's streams."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from repositories import ActivityRepository
    activity_repo = ActivityRepository()
    activity = activity_repo.find_one_by(strava_id=activity_id, user_id=user.id)

    if not activity:
        return jsonify({'error': 'Activity not found'}), 404

    streams = activity.streams
    if not streams:
        return jsonify({'error': 'Activity has no stream data'}), 400

    if len(streams.get('latlng') or []) < 10:
        return jsonify({'error': 'Insufficient route data in activity'}), 400

    data = request.get_json(silent=True) or {}
    from services.route_suggestion_service import build_route_from_activity
    route = build_route_from_activity(activity, user.id, name=data.get('name'))

    route_repo.create(route)

    # Enrich asynchronously-ish (terrain summary)
    try:
        _enrich_route(route)
        route_repo.commit()
    except Exception:
        route_repo.commit()  # save route even if enrichment fails

    return jsonify(route.to_dict()), 201


@bp.route('/<int:route_id>', methods=['PATCH'])
def update_route(route_id):
    """Update route metadata (name, tags)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    route = route_repo.get_user_route(route_id, user.id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'name' in data:
        route.name = data['name']
    if 'tags' in data:
        route.tags = data['tags']

    route_repo.commit()
    return jsonify(route.to_summary())


@bp.route('/<int:route_id>', methods=['DELETE'])
def delete_route(route_id):
    """Delete a training route."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    route = route_repo.get_user_route(route_id, user.id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404

    route_repo.delete(route)
    route_repo.commit()
    return jsonify({'status': 'deleted', 'id': route_id})


@bp.route('/generate', methods=['POST'])
def generate_route():
    """Generate a loop route via OpenRouteService."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    center_lat = data.get('center_lat')
    center_lon = data.get('center_lon')
    target_distance_km = data.get('target_distance_km', 10)
    target_elevation_m = data.get('target_elevation_m')

    if center_lat is None or center_lon is None:
        return jsonify({'error': 'center_lat and center_lon are required'}), 400

    from services.route_generation_service import RouteGenerationService
    service = RouteGenerationService()

    result = service.generate_loop_route(
        center_lat=center_lat,
        center_lon=center_lon,
        target_distance_km=target_distance_km,
        target_elevation_m=target_elevation_m,
        route_type=data.get('route_type', 'loop'),
        preferred_direction=data.get('preferred_direction'),
    )

    if 'error' in result:
        return jsonify(result), 400

    # Save the generated route
    from models.training_route import TrainingRoute
    name = data.get('name', f"Generated {target_distance_km}km loop")
    tags = _auto_tag(result['distance_km'], result['elevation_gain_m'])

    route = TrainingRoute(
        user_id=user.id,
        name=name,
        source='generated',
        route_data=result['route_data'],
        distance_km=result['distance_km'],
        elevation_gain_m=result['elevation_gain_m'],
        elevation_loss_m=result['elevation_loss_m'],
        center_lat=round(center_lat, 6),
        center_lon=round(center_lon, 6),
        tags=tags,
        generation_params={
            'center_lat': center_lat,
            'center_lon': center_lon,
            'target_distance_km': target_distance_km,
            'target_elevation_m': target_elevation_m,
        },
    )

    route_repo.create(route)

    try:
        _enrich_route(route)
        route_repo.commit()
    except Exception:
        route_repo.commit()

    return jsonify(route.to_dict()), 201


@bp.route('/generate-stream', methods=['POST'])
def generate_route_stream():
    """Generate a loop route via ORS, streaming progress as NDJSON.

    Each line of the response body is a JSON event:
      {"type":"attempt","iteration":1,"max_iterations":3,"scale":1.0}
      {"type":"result","iteration":1,"distance_km":...,"distance_error_pct":...,"cached":true}
      {"type":"complete","route":{"id":42,"distance_km":...,...}}
      {"type":"error","error":"..."}

    The frontend reads the body as a stream so it can update the progress UI
    while the iterations are still running. The route is saved on the final
    'complete' event and its DB id is included in the payload.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    center_lat = data.get('center_lat')
    center_lon = data.get('center_lon')
    target_distance_km = data.get('target_distance_km', 10)
    target_elevation_m = data.get('target_elevation_m')
    route_type = data.get('route_type', 'loop')
    preferred_direction = data.get('preferred_direction')
    name = data.get('name')

    if center_lat is None or center_lon is None:
        return jsonify({'error': 'center_lat and center_lon are required'}), 400

    user_id = user.id

    from services.route_generation_service import RouteGenerationService
    from models.training_route import TrainingRoute
    from database import db

    service = RouteGenerationService()

    def event_stream():
        final_route_dict = None
        last_route = None
        try:
            for event in service.generate_loop_route_stream(
                center_lat=center_lat,
                center_lon=center_lon,
                target_distance_km=target_distance_km,
                target_elevation_m=target_elevation_m,
                route_type=route_type,
                preferred_direction=preferred_direction,
            ):
                if event.get('type') == 'complete':
                    last_route = event.get('route')
                    continue  # we'll emit our own 'complete' after persisting
                yield json.dumps(event) + '\n'

            if not last_route:
                yield json.dumps({'type': 'error', 'error': 'no result produced'}) + '\n'
                return

            display_name = name or (
                f"{target_distance_km}km "
                f"{'out & back' if route_type == 'out_and_back' else 'loop'}"
            )
            tags = _auto_tag(last_route['distance_km'], last_route['elevation_gain_m'])

            route = TrainingRoute(
                user_id=user_id,
                name=display_name,
                source='generated',
                route_data=last_route['route_data'],
                distance_km=last_route['distance_km'],
                elevation_gain_m=last_route['elevation_gain_m'],
                elevation_loss_m=last_route['elevation_loss_m'],
                center_lat=round(center_lat, 6),
                center_lon=round(center_lon, 6),
                tags=tags,
                generation_params={
                    'center_lat': center_lat,
                    'center_lon': center_lon,
                    'target_distance_km': target_distance_km,
                    'target_elevation_m': target_elevation_m,
                    'route_type': route_type,
                    'preferred_direction': preferred_direction,
                },
            )
            route_repo.create(route)
            try:
                _enrich_route(route)
            except Exception:
                pass
            db.session.commit()
            final_route_dict = route.to_dict()

            yield json.dumps({'type': 'complete', 'route': final_route_dict}) + '\n'
        except Exception as e:
            db.session.rollback()
            yield json.dumps({'type': 'error', 'error': str(e)}) + '\n'

    return Response(stream_with_context(event_stream()), mimetype='application/x-ndjson')


@bp.route('/frequent', methods=['GET'])
def list_frequent_routes():
    """Return clusters of recurring routes inferred from imported activities.

    Zero ORS calls — pure aggregation over Activity streams.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    limit = request.args.get('limit', default=10, type=int)
    limit = max(1, min(50, limit))

    from services.route_suggestion_service import find_frequent_routes
    suggestions = find_frequent_routes(user.id, limit=limit)
    return jsonify({'suggestions': suggestions})


@bp.route('/from-waypoints', methods=['POST'])
def generate_from_waypoints():
    """Generate a route through user-specified waypoints via ORS."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'waypoints' not in data:
        return jsonify({'error': 'waypoints required'}), 400

    waypoints = data['waypoints']
    if len(waypoints) < 2:
        return jsonify({'error': 'At least 2 waypoints required'}), 400

    from services.route_generation_service import RouteGenerationService
    service = RouteGenerationService()

    result = service.generate_route_from_waypoints(waypoints)
    if 'error' in result:
        return jsonify(result), 400

    from models.training_route import TrainingRoute
    name = data.get('name', 'Custom route')
    tags = _auto_tag(result['distance_km'], result['elevation_gain_m'])

    lats = [w[0] if isinstance(w, list) else w['lat'] for w in waypoints]
    lons = [w[1] if isinstance(w, list) else w['lon'] for w in waypoints]

    route = TrainingRoute(
        user_id=user.id,
        name=name,
        source='generated',
        route_data=result['route_data'],
        distance_km=result['distance_km'],
        elevation_gain_m=result['elevation_gain_m'],
        elevation_loss_m=result['elevation_loss_m'],
        center_lat=round(sum(lats) / len(lats), 6),
        center_lon=round(sum(lons) / len(lons), 6),
        tags=tags,
        generation_params={'waypoints': waypoints},
    )

    route_repo.create(route)

    try:
        _enrich_route(route)
        route_repo.commit()
    except Exception:
        route_repo.commit()

    return jsonify(route.to_dict()), 201


def _location_payload(data, loc=None):
    """Validate a location body; returns (fields, error)."""
    out = {}
    for k in ('lat', 'lon', 'radius_km'):
        if k in data:
            try:
                out[k] = float(data[k])
            except (TypeError, ValueError):
                return None, f'{k} must be numeric'
    if 'name' in data:
        out['name'] = (data['name'] or '').strip()[:255]
    if loc is None and not {'lat', 'lon', 'name'} <= out.keys():
        return None, 'name, lat and lon are required'
    if out.get('radius_km', 1) <= 0 or out.get('name', 'x') == '':
        return None, 'invalid name or radius_km'
    return out, None


def _rematch_plans(user_id):
    from repositories import UserTrainingPreferencesRepository
    from services.route_matcher import rematch_future_plan_days
    rematch_future_plan_days(user_id, UserTrainingPreferencesRepository().get_by_user(user_id))


@bp.route('/locations', methods=['GET'])
def list_locations():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'locations': [l.to_dict() for l in location_repo.get_user_locations(user.id)]})


@bp.route('/locations', methods=['POST'])
def create_location():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    fields, err = _location_payload(request.get_json() or {})
    if err:
        return jsonify({'error': err}), 400
    loc = TrainingLocation(user_id=user.id, weekdays=[], **fields)
    if 'radius_km' not in fields:
        loc.radius_km = 10
    location_repo.create(loc)
    location_repo.assign_weekdays(user.id, loc, (request.get_json() or {}).get('weekdays') or [])
    _rematch_plans(user.id)
    location_repo.commit()
    return jsonify(loc.to_dict()), 201


@bp.route('/locations/<int:location_id>', methods=['PATCH'])
def update_location(location_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    loc = location_repo.get_user_location(location_id, user.id)
    if not loc:
        return jsonify({'error': 'Location not found'}), 404
    data = request.get_json() or {}
    fields, err = _location_payload(data, loc)
    if err:
        return jsonify({'error': err}), 400
    for k, v in fields.items():
        setattr(loc, k, v)
    if 'weekdays' in data:
        location_repo.assign_weekdays(user.id, loc, data['weekdays'] or [])
    _rematch_plans(user.id)
    location_repo.commit()
    return jsonify(loc.to_dict())


@bp.route('/locations/<int:location_id>', methods=['DELETE'])
def delete_location(location_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    loc = location_repo.get_user_location(location_id, user.id)
    if not loc:
        return jsonify({'error': 'Location not found'}), 404
    location_repo.delete(loc)
    location_repo.commit()
    return jsonify({'ok': True})


@bp.route('/training-location', methods=['GET'])
def get_training_location():
    """Get user's training base location."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    location = {
        'lat': user.training_base_lat,
        'lon': user.training_base_lon,
        'name': user.training_base_name,
        'radius_km': user.training_travel_radius_km or 30,
    }

    # If no location set, try to infer from Strava
    if not user.training_base_lat:
        from services.route_generation_service import RouteGenerationService
        service = RouteGenerationService()
        inferred = service.infer_training_base(user.id)
        if inferred:
            location['inferred'] = inferred

    return jsonify(location)


@bp.route('/training-location', methods=['PUT'])
def set_training_location():
    """Set user's training base location."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'lat' not in data or 'lon' not in data:
        return jsonify({'error': 'lat and lon are required'}), 400

    from database import db
    user.training_base_lat = data['lat']
    user.training_base_lon = data['lon']
    user.training_base_name = data.get('name')
    if 'radius_km' in data:
        user.training_travel_radius_km = data['radius_km']

    db.session.commit()

    return jsonify({
        'lat': user.training_base_lat,
        'lon': user.training_base_lon,
        'name': user.training_base_name,
        'radius_km': user.training_travel_radius_km,
    })


@bp.route('/search', methods=['GET'])
def search_routes():
    """Search routes by criteria."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    min_dist = request.args.get('min_distance_km', type=float)
    max_dist = request.args.get('max_distance_km', type=float)
    min_elev = request.args.get('min_elevation_m', type=float)
    max_elev = request.args.get('max_elevation_m', type=float)

    routes = route_repo.search_by_criteria(
        user.id,
        min_distance_km=min_dist,
        max_distance_km=max_dist,
        min_elevation_m=min_elev,
        max_elevation_m=max_elev,
    )
    return jsonify({'routes': [r.to_summary() for r in routes]})


@bp.route('/preview', methods=['POST'])
def preview_route():
    """Preview a route through waypoints without saving (for interactive map editing)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'waypoints' not in data:
        return jsonify({'error': 'waypoints required'}), 400

    waypoints = data['waypoints']
    if len(waypoints) < 2:
        return jsonify({'error': 'At least 2 waypoints required'}), 400

    from services.route_generation_service import RouteGenerationService
    service = RouteGenerationService()

    result = service.generate_route_from_waypoints(waypoints)
    if 'error' in result:
        return jsonify(result), 400

    return jsonify(result)


@bp.route('/build-steps', methods=['POST'])
def build_steps():
    """Build workout steps from a route."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'route_id' not in data:
        return jsonify({'error': 'route_id is required'}), 400

    # Verify route belongs to user
    route = route_repo.get_user_route(data['route_id'], user.id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404

    from services.workout_service import build_steps_from_route
    steps = build_steps_from_route(
        route_id=data['route_id'],
        workout_type=data.get('workout_type', 'long_run'),
        focus=data.get('focus', 'climbing'),
    )

    return jsonify({'steps': steps})


@bp.route('/suggest', methods=['GET'])
def suggest_routes():
    """Suggest routes for a workout based on type, distance, and elevation."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    workout_type = request.args.get('workout_type', 'long_run')
    target_distance_km = request.args.get('target_distance_km', type=float)
    target_elevation_m = request.args.get('target_elevation_m', type=float)

    from services.route_generation_service import RouteGenerationService
    service = RouteGenerationService()

    suggestions = service.suggest_routes_for_workout(
        user_id=user.id,
        workout_type=workout_type,
        target_distance_km=target_distance_km,
        target_elevation_m=target_elevation_m,
    )

    return jsonify({'suggestions': suggestions})


def _auto_tag(distance_km, elevation_gain_m):
    """Generate automatic tags based on route stats."""
    tags = []
    if distance_km > 0:
        ratio = elevation_gain_m / distance_km if distance_km > 0 else 0
        if ratio > 60:
            tags.append('hilly')
        elif ratio < 15:
            tags.append('flat')

        if distance_km > 30:
            tags.append('ultra')
        elif distance_km > 15:
            tags.append('long')

        if elevation_gain_m > 1500:
            tags.append('high_vert')

    return tags


def _enrich_route(route):
    """Enrich route with terrain summary. Best-effort, non-blocking."""
    try:
        from services.osm_terrain_service import OSMTerrainService
        terrain_service = OSMTerrainService()
        points = route.route_data

        # Sample points for terrain query (max 50 for API limits)
        step = max(1, len(points) // 50)
        sampled = points[::step]

        terrain_data = terrain_service.get_terrain_for_route(sampled)
        if terrain_data:
            # Summarize terrain types
            from collections import Counter
            categories = [t.get('category', 'unknown') for t in terrain_data if t]
            summary = dict(Counter(categories))
            total = sum(summary.values())
            route.terrain_summary = {
                k: round(v / total * 100) for k, v in summary.items()
            } if total > 0 else {}
    except Exception:
        pass  # terrain enrichment is optional

"""Route generation service using OpenRouteService API."""

import hashlib
import json
import math
import os
import logging
import random
import requests
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

ORS_BASE_URL = "https://api.openrouteservice.org/v2"
ORS_DAILY_LIMIT = 2000

# Maximum iterations for loop refinement (each costs 1 ORS call when not cached)
MAX_LOOP_ITERATIONS = 3

# How long to cache an ORS routing response. The underlying road/trail graph
# changes slowly; 7 days is a safe default for repeated previews and identical
# auto-generation requests.
ROUTE_CACHE_TTL_DAYS = 7

# Coordinate rounding for cache key. 5 decimals ≈ 1.1m — fine enough that
# tiny float jitter from the frontend doesn't bust the cache, coarse enough
# that genuinely different waypoints get different keys.
_CACHE_COORD_DECIMALS = 5


class RouteGenerationService:
    def __init__(self):
        self.api_key = os.getenv('ORS_API_KEY')

    # ------------------------------------------------------------------
    # Loop generation
    # ------------------------------------------------------------------

    def generate_loop_route(
        self,
        center_lat: float,
        center_lon: float,
        target_distance_km: float = 10,
        target_elevation_m: Optional[float] = None,
        route_type: str = 'loop',
        preferred_direction: Optional[float] = None,
    ) -> Dict:
        """Generate a loop or out-and-back route. Synchronous wrapper around the
        streaming variant — consumes the generator and returns the final result.
        """
        result = None
        for event in self.generate_loop_route_stream(
            center_lat=center_lat,
            center_lon=center_lon,
            target_distance_km=target_distance_km,
            target_elevation_m=target_elevation_m,
            route_type=route_type,
            preferred_direction=preferred_direction,
        ):
            if event.get('type') == 'complete':
                result = event.get('route')
            elif event.get('type') == 'error':
                return {'error': event.get('error', 'route generation failed')}
        return result or {'error': 'no result produced'}

    def generate_loop_route_stream(
        self,
        center_lat: float,
        center_lon: float,
        target_distance_km: float = 10,
        target_elevation_m: Optional[float] = None,
        route_type: str = 'loop',
        preferred_direction: Optional[float] = None,
    ) -> Iterable[Dict]:
        """Generator yielding progress events while iteratively refining a loop.

        Events emitted (each is a plain dict, suitable for NDJSON serialization):
          - {type: 'attempt', iteration: 1, max_iterations: 3, scale: 1.0}
          - {type: 'result', iteration: 1, distance_km, elevation_gain_m,
                          distance_error_pct, elev_error_pct, cached: bool}
          - {type: 'complete', route: {route_data, distance_km, ...}}
          - {type: 'error', error: '...'}
        """
        if not self.api_key:
            yield {'type': 'error', 'error': 'ORS_API_KEY not configured'}
            return

        if route_type == 'out_and_back':
            yield {'type': 'attempt', 'iteration': 1, 'max_iterations': 1, 'scale': 1.0}
            result = self._generate_out_and_back(
                center_lat, center_lon, target_distance_km, preferred_direction
            )
            if 'error' in result:
                yield {'type': 'error', 'error': result['error']}
                return
            yield {
                'type': 'result',
                'iteration': 1,
                'distance_km': result.get('distance_km'),
                'elevation_gain_m': result.get('elevation_gain_m'),
                'distance_error_pct': self._pct_err(result.get('distance_km'), target_distance_km),
                'elev_error_pct': self._pct_err(result.get('elevation_gain_m'), target_elevation_m),
                'cached': result.pop('_cached', False),
            }
            yield {'type': 'complete', 'route': result}
            return

        direction = preferred_direction if preferred_direction is not None else random.uniform(0, 360)
        waypoints = self._create_lobe_waypoints(
            center_lat, center_lon, target_distance_km, direction
        )

        best_result = None
        best_distance_error = float('inf')
        scale_factor = 1.0

        for iteration in range(MAX_LOOP_ITERATIONS):
            if iteration > 0 and best_result and best_result.get('distance_km'):
                actual = best_result['distance_km']
                scale_factor *= target_distance_km / actual
                scale_factor = max(0.5, min(2.0, scale_factor))
                waypoints = self._create_lobe_waypoints(
                    center_lat, center_lon, target_distance_km * scale_factor, direction
                )

            yield {
                'type': 'attempt',
                'iteration': iteration + 1,
                'max_iterations': MAX_LOOP_ITERATIONS,
                'scale': round(scale_factor, 3),
            }

            result = self.generate_route_from_waypoints(waypoints)
            if 'error' in result:
                if best_result:
                    yield {'type': 'complete', 'route': best_result}
                    return
                yield {'type': 'error', 'error': result['error']}
                return

            distance_error = abs(result['distance_km'] - target_distance_km)
            distance_error_pct = distance_error / target_distance_km

            elev_ok = True
            elev_error_pct = None
            if target_elevation_m and result.get('elevation_gain_m'):
                elev_error_pct = abs(result['elevation_gain_m'] - target_elevation_m) / target_elevation_m
                elev_ok = elev_error_pct < 0.3

            if distance_error < best_distance_error:
                best_distance_error = distance_error
                best_result = result

            yield {
                'type': 'result',
                'iteration': iteration + 1,
                'distance_km': result.get('distance_km'),
                'elevation_gain_m': result.get('elevation_gain_m'),
                'distance_error_pct': round(distance_error_pct, 3),
                'elev_error_pct': round(elev_error_pct, 3) if elev_error_pct is not None else None,
                'cached': result.get('_cached', False),
            }

            if distance_error_pct < 0.10 and elev_ok:
                break

        # Optional perpendicular fallback when elevation target is far off.
        if (target_elevation_m and best_result
                and best_result.get('elevation_gain_m')
                and abs(best_result['elevation_gain_m'] - target_elevation_m) / target_elevation_m > 0.3):
            alt_direction = (direction + 90) % 360
            alt_waypoints = self._create_lobe_waypoints(
                center_lat, center_lon, target_distance_km * scale_factor, alt_direction
            )
            yield {
                'type': 'attempt',
                'iteration': MAX_LOOP_ITERATIONS + 1,
                'max_iterations': MAX_LOOP_ITERATIONS + 1,
                'scale': round(scale_factor, 3),
                'note': 'perpendicular_retry',
            }
            alt_result = self.generate_route_from_waypoints(alt_waypoints)
            if 'error' not in alt_result:
                current_elev_err = abs(best_result['elevation_gain_m'] - target_elevation_m)
                alt_elev_err = abs(alt_result.get('elevation_gain_m', 0) - target_elevation_m)
                yield {
                    'type': 'result',
                    'iteration': MAX_LOOP_ITERATIONS + 1,
                    'distance_km': alt_result.get('distance_km'),
                    'elevation_gain_m': alt_result.get('elevation_gain_m'),
                    'distance_error_pct': self._pct_err(alt_result.get('distance_km'), target_distance_km),
                    'elev_error_pct': self._pct_err(alt_result.get('elevation_gain_m'), target_elevation_m),
                    'cached': alt_result.get('_cached', False),
                }
                if alt_elev_err < current_elev_err:
                    best_result = alt_result

        if best_result:
            best_result.pop('_cached', None)
            yield {'type': 'complete', 'route': best_result}
        else:
            yield {'type': 'error', 'error': 'no result produced'}

    @staticmethod
    def _pct_err(actual, target):
        if not actual or not target:
            return None
        return round(abs(actual - target) / target, 3)

    # ------------------------------------------------------------------
    # Waypoint shaping
    # ------------------------------------------------------------------

    def _create_lobe_waypoints(
        self,
        start_lat: float,
        start_lon: float,
        effective_distance_km: float,
        direction_deg: float,
    ) -> List:
        """Create teardrop/lobe-shaped waypoints that avoid back-and-forth paths."""
        ROUTING_OVERHEAD = 1.6
        straight_line_perimeter = effective_distance_km / ROUTING_OVERHEAD
        lobe_length = straight_line_perimeter * 0.35
        lobe_width = lobe_length * 0.4
        n_waypoints = max(5, min(10, int(effective_distance_km / 2)))

        km_per_deg_lat = 111.0
        km_per_deg_lon = 111.0 * max(math.cos(math.radians(start_lat)), 0.1)
        dir_rad = math.radians(direction_deg)

        waypoints = []
        half = n_waypoints // 2

        for i in range(half):
            t = (i + 1) / half
            along = lobe_length * t
            lateral = lobe_width * math.sin(t * math.pi) * 0.5
            lat_offset = (along * math.cos(dir_rad) - lateral * math.sin(dir_rad)) / km_per_deg_lat
            lon_offset = (along * math.sin(dir_rad) + lateral * math.cos(dir_rad)) / km_per_deg_lon
            waypoints.append([start_lat + lat_offset, start_lon + lon_offset])

        for i in range(half - 1, -1, -1):
            t = (i + 1) / half
            along = lobe_length * t
            lateral = -lobe_width * math.sin(t * math.pi) * 0.5
            lat_offset = (along * math.cos(dir_rad) - lateral * math.sin(dir_rad)) / km_per_deg_lat
            lon_offset = (along * math.sin(dir_rad) + lateral * math.cos(dir_rad)) / km_per_deg_lon
            waypoints.append([start_lat + lat_offset, start_lon + lon_offset])

        waypoints.insert(0, [start_lat, start_lon])
        waypoints.append([start_lat, start_lon])

        return waypoints

    def _generate_out_and_back(
        self,
        start_lat: float,
        start_lon: float,
        target_distance_km: float,
        direction_deg: Optional[float] = None,
    ) -> Dict:
        if not self.api_key:
            return {'error': 'ORS_API_KEY not configured'}

        direction = direction_deg if direction_deg is not None else random.uniform(0, 360)
        dir_rad = math.radians(direction)

        ROUTING_OVERHEAD = 1.6
        one_way_km = target_distance_km / (2 * ROUTING_OVERHEAD)

        km_per_deg_lat = 111.0
        km_per_deg_lon = 111.0 * max(math.cos(math.radians(start_lat)), 0.1)

        n_points = max(2, min(4, int(target_distance_km / 5)))
        waypoints = [[start_lat, start_lon]]

        for i in range(1, n_points + 1):
            t = i / n_points
            dist = one_way_km * t
            jitter = random.uniform(-0.1, 0.1) * one_way_km
            lat_off = (dist * math.cos(dir_rad) + jitter * math.sin(dir_rad)) / km_per_deg_lat
            lon_off = (dist * math.sin(dir_rad) - jitter * math.cos(dir_rad)) / km_per_deg_lon
            waypoints.append([start_lat + lat_off, start_lon + lon_off])

        for wp in reversed(waypoints[:-1]):
            waypoints.append(wp)

        return self.generate_route_from_waypoints(waypoints)

    # ------------------------------------------------------------------
    # ORS call + cache
    # ------------------------------------------------------------------

    def generate_route_from_waypoints(self, waypoints: List) -> Dict:
        """Generate route through waypoints. Hits the ORS cache first."""
        if not self.api_key:
            return {'error': 'ORS_API_KEY not configured'}

        coordinates = self._normalize_to_lonlat(waypoints)
        cache_key = self._cache_key(coordinates)

        cached = self._cache_get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached['_cached'] = True
            return cached

        try:
            response = requests.post(
                f"{ORS_BASE_URL}/directions/foot-hiking/geojson",
                json={
                    "coordinates": coordinates,
                    "elevation": True,
                    "instructions": False,
                },
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"ORS API error {response.status_code}: {response.text[:500]}")
                return {'error': f'ORS API error: {response.status_code}'}

            data = response.json()

        except requests.RequestException as e:
            logger.error(f"ORS request failed: {e}")
            return {'error': f'ORS request failed: {str(e)}'}

        try:
            feature = data['features'][0]
            coords = feature['geometry']['coordinates']
        except (KeyError, IndexError) as e:
            return {'error': f'Invalid ORS response: {e}'}

        route_data = []
        cum_distance = 0.0

        for i, coord in enumerate(coords):
            lon, lat = coord[0], coord[1]
            elevation = coord[2] if len(coord) > 2 else 0
            if i > 0:
                prev = coords[i - 1]
                cum_distance += _haversine(prev[1], prev[0], lat, lon)
            route_data.append({
                'lat': round(lat, 6),
                'lon': round(lon, 6),
                'elevation': round(elevation, 1),
                'distance': round(cum_distance, 1),
            })

        elevations = np.array([p['elevation'] for p in route_data])
        elev_diffs = np.diff(elevations)
        elevation_gain = float(np.sum(elev_diffs[elev_diffs > 0]))
        elevation_loss = float(np.abs(np.sum(elev_diffs[elev_diffs < 0])))
        distance_km = cum_distance / 1000

        result = {
            'route_data': route_data,
            'distance_km': round(distance_km, 2),
            'elevation_gain_m': round(elevation_gain),
            'elevation_loss_m': round(elevation_loss),
        }

        self._cache_set(cache_key, result)
        return result

    @staticmethod
    def _normalize_to_lonlat(waypoints: List) -> List[List[float]]:
        coordinates = []
        for wp in waypoints:
            if isinstance(wp, dict):
                coordinates.append([wp['lon'], wp['lat']])
            elif isinstance(wp, (list, tuple)):
                coordinates.append([wp[1], wp[0]])
        return coordinates

    @staticmethod
    def _cache_key(coordinates: List[List[float]]) -> str:
        rounded = [
            [round(c[0], _CACHE_COORD_DECIMALS), round(c[1], _CACHE_COORD_DECIMALS)]
            for c in coordinates
        ]
        payload = json.dumps({'wp': rounded, 'profile': 'foot-hiking', 'v': 1}, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def _cache_get(cache_key: str) -> Optional[dict]:
        try:
            from repositories import RouteCacheRepository
            repo = RouteCacheRepository()
            return repo.get_cached(cache_key)
        except Exception as e:
            logger.warning(f"route cache get failed: {e}")
            return None

    @staticmethod
    def _cache_set(cache_key: str, data: dict) -> None:
        try:
            from repositories import RouteCacheRepository
            repo = RouteCacheRepository()
            expires_at = datetime.now(timezone.utc) + timedelta(days=ROUTE_CACHE_TTL_DAYS)
            repo.set_cached(cache_key, data, expires_at)
            repo.commit()
        except Exception as e:
            logger.warning(f"route cache set failed: {e}")

    # ------------------------------------------------------------------
    # Suggestion / inference (existing functionality)
    # ------------------------------------------------------------------

    def suggest_routes_for_workout(
        self,
        user_id: int,
        workout_type: str,
        target_distance_km: Optional[float] = None,
        target_elevation_m: Optional[float] = None,
    ) -> List[Dict]:
        from repositories.training_route_repository import TrainingRouteRepository
        repo = TrainingRouteRepository()

        routes = repo.get_user_routes(user_id)
        if not routes:
            return []

        scored = []
        for route in routes:
            score = self._score_route_for_workout(
                route, workout_type, target_distance_km, target_elevation_m
            )
            scored.append({
                'route': route.to_summary(),
                'score': score,
                'match_reasons': self._match_reasons(
                    route, workout_type, target_distance_km, target_elevation_m
                ),
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:5]

    def _score_route_for_workout(
        self,
        route,
        workout_type: str,
        target_distance_km: Optional[float],
        target_elevation_m: Optional[float],
    ) -> float:
        score = 50.0

        if target_distance_km and route.distance_km:
            dist_ratio = route.distance_km / target_distance_km
            if 0.8 <= dist_ratio <= 1.2:
                score += 40 * (1 - abs(1 - dist_ratio) / 0.2)
            elif 0.5 <= dist_ratio <= 1.5:
                score += 20 * (1 - abs(1 - dist_ratio) / 0.5)

        if target_elevation_m and route.elevation_gain_m:
            elev_ratio = route.elevation_gain_m / target_elevation_m
            if 0.7 <= elev_ratio <= 1.3:
                score += 30 * (1 - abs(1 - elev_ratio) / 0.3)
            elif 0.4 <= elev_ratio <= 1.6:
                score += 15 * (1 - abs(1 - elev_ratio) / 0.6)

        tags = route.tags or []
        if workout_type in ('hill_repeats', 'mountain_run') and 'hilly' in tags:
            score += 30
        elif workout_type in ('hill_repeats', 'mountain_run') and 'high_vert' in tags:
            score += 25
        elif workout_type in ('easy', 'recovery') and 'flat' in tags:
            score += 25
        elif workout_type == 'long_run' and ('long' in tags or 'ultra' in tags):
            score += 20
        elif workout_type == 'tempo' and 'flat' in tags:
            score += 20

        return min(100.0, max(0.0, score))

    def _match_reasons(
        self,
        route,
        workout_type: str,
        target_distance_km: Optional[float],
        target_elevation_m: Optional[float],
    ) -> List[str]:
        reasons = []

        if target_distance_km and route.distance_km:
            pct = abs(route.distance_km - target_distance_km) / target_distance_km * 100
            if pct < 10:
                reasons.append(f"Distance matches ({route.distance_km} km)")
            elif pct < 25:
                reasons.append(f"Close distance ({route.distance_km} km vs {target_distance_km} km target)")

        if target_elevation_m and route.elevation_gain_m:
            pct = abs(route.elevation_gain_m - target_elevation_m) / target_elevation_m * 100
            if pct < 15:
                reasons.append(f"Elevation matches ({route.elevation_gain_m}m D+)")
            elif pct < 30:
                reasons.append(f"Similar elevation ({route.elevation_gain_m}m vs {target_elevation_m}m target)")

        tags = route.tags or []
        if workout_type in ('hill_repeats', 'mountain_run') and ('hilly' in tags or 'high_vert' in tags):
            reasons.append("Good for hill training")
        elif workout_type in ('easy', 'recovery') and 'flat' in tags:
            reasons.append("Flat terrain for easy effort")
        elif workout_type == 'long_run' and ('long' in tags or 'ultra' in tags):
            reasons.append("Suitable distance for long run")

        if route.terrain_summary:
            dominant = max(route.terrain_summary.items(), key=lambda x: x[1], default=None)
            if dominant:
                reasons.append(f"Mainly {dominant[0]} ({dominant[1]}%)")

        return reasons

    def infer_training_base(self, user_id: int) -> Optional[Dict]:
        from repositories import ActivityRepository

        repo = ActivityRepository()
        activities = repo.find_by(user_id=user_id)

        locations = []
        for act in activities[-30:]:
            streams = act.streams
            if streams and 'latlng' in streams and streams['latlng']:
                start = streams['latlng'][0]
                locations.append(start)

        if not locations:
            return None

        lats = [loc[0] for loc in locations]
        lons = [loc[1] for loc in locations]

        return {
            'lat': round(sum(lats) / len(lats), 6),
            'lon': round(sum(lons) / len(lons), 6),
            'activity_count': len(locations),
        }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

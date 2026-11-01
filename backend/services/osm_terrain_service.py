"""OSM terrain enrichment service using Overpass API.

Matches GPX route points to OpenStreetMap way data to determine
surface types (asphalt, gravel, dirt, rock, mud) and trail classifications.
This enables per-segment terrain factors instead of static defaults.

Uses the free Overpass API (no API key needed).
"""

import requests
import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from repositories import TerrainCacheRepository

logger = logging.getLogger(__name__)

# Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# The main instance throttles by refusing connections from a busy IP; the
# mirror keeps terrain working meanwhile. Tried in order.
# TODO(deploy-review #22 — see GH issues): public Overpass refuses busy IPs and the
# mirror times out on real bboxes, so terrain degrades to "unknown". Fix: retry later
# with a short-TTL cache entry, throttle calls, or self-host Overpass for production.
OVERPASS_URLS = (OVERPASS_URL, "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
# overpass-api.de answers 406 to generic clients (python-requests included).
OVERPASS_HEADERS = {"User-Agent": "PaceMind/1.0 (trail route analysis)"}

# Cache TTL (OSM data changes slowly)
TERRAIN_CACHE_TTL_DAYS = 30

# Surface type to terrain factor mapping
# Based on empirical trail running performance data
SURFACE_FACTORS = {
    # Paved surfaces (baseline)
    'asphalt': {'k_terrain_up': 1.00, 'k_terrain_down': 1.00, 'k_terrain_flat': 1.00, 'category': 'road'},
    'paved': {'k_terrain_up': 1.00, 'k_terrain_down': 1.00, 'k_terrain_flat': 1.00, 'category': 'road'},
    'concrete': {'k_terrain_up': 1.00, 'k_terrain_down': 1.00, 'k_terrain_flat': 1.00, 'category': 'road'},

    # Compact gravel (fast trails)
    'compacted': {'k_terrain_up': 1.03, 'k_terrain_down': 1.05, 'k_terrain_flat': 1.03, 'category': 'gravel'},
    'fine_gravel': {'k_terrain_up': 1.04, 'k_terrain_down': 1.06, 'k_terrain_flat': 1.04, 'category': 'gravel'},
    'gravel': {'k_terrain_up': 1.05, 'k_terrain_down': 1.08, 'k_terrain_flat': 1.05, 'category': 'gravel'},

    # Dirt/earth (typical trails)
    'ground': {'k_terrain_up': 1.08, 'k_terrain_down': 1.10, 'k_terrain_flat': 1.06, 'category': 'trail'},
    'dirt': {'k_terrain_up': 1.08, 'k_terrain_down': 1.10, 'k_terrain_flat': 1.06, 'category': 'trail'},
    'earth': {'k_terrain_up': 1.08, 'k_terrain_down': 1.10, 'k_terrain_flat': 1.06, 'category': 'trail'},
    'unpaved': {'k_terrain_up': 1.08, 'k_terrain_down': 1.10, 'k_terrain_flat': 1.06, 'category': 'trail'},

    # Grass/meadow
    'grass': {'k_terrain_up': 1.10, 'k_terrain_down': 1.12, 'k_terrain_flat': 1.08, 'category': 'trail'},

    # Rocky/technical
    'rock': {'k_terrain_up': 1.15, 'k_terrain_down': 1.20, 'k_terrain_flat': 1.12, 'category': 'technical'},
    'stones': {'k_terrain_up': 1.15, 'k_terrain_down': 1.20, 'k_terrain_flat': 1.12, 'category': 'technical'},
    'pebblestone': {'k_terrain_up': 1.12, 'k_terrain_down': 1.18, 'k_terrain_flat': 1.10, 'category': 'technical'},

    # Mud (worst case)
    'mud': {'k_terrain_up': 1.20, 'k_terrain_down': 1.25, 'k_terrain_flat': 1.18, 'category': 'mud'},

    # Sand
    'sand': {'k_terrain_up': 1.25, 'k_terrain_down': 1.15, 'k_terrain_flat': 1.20, 'category': 'technical'},
}

# Highway type fallbacks (when surface tag is missing)
HIGHWAY_FACTORS = {
    'motorway': SURFACE_FACTORS['asphalt'],
    'trunk': SURFACE_FACTORS['asphalt'],
    'primary': SURFACE_FACTORS['asphalt'],
    'secondary': SURFACE_FACTORS['asphalt'],
    'tertiary': SURFACE_FACTORS['asphalt'],
    'residential': SURFACE_FACTORS['asphalt'],
    'track': SURFACE_FACTORS['ground'],
    'path': SURFACE_FACTORS['ground'],
    'footway': SURFACE_FACTORS['ground'],
    'bridleway': SURFACE_FACTORS['ground'],
    'cycleway': SURFACE_FACTORS['asphalt'],
    'steps': SURFACE_FACTORS['rock'],
}

# SAC scale hiking difficulty -> additional factor multiplier
SAC_SCALE_MULTIPLIERS = {
    'hiking': 1.00,          # T1 - well maintained trails
    'mountain_hiking': 1.05, # T2 - mountain paths
    'demanding_mountain_hiking': 1.12, # T3 - exposed, scrambling
    'alpine_hiking': 1.20,   # T4 - alpine, hands needed
    'demanding_alpine_hiking': 1.30,   # T5 - demanding alpine
    'difficult_alpine_hiking': 1.40,   # T6 - difficult alpine
}

# Default factors when no OSM data available
DEFAULT_TERRAIN = {
    'k_terrain_up': 1.08,
    'k_terrain_down': 1.12,
    'k_terrain_flat': 1.05,
    'surface_type': 'unknown',
    'category': 'unknown',
}


from models.terrain_cache import TerrainCache


class OSMTerrainService:
    """Fetch and match OSM terrain data to GPX route points."""

    def __init__(self, terrain_cache_repo=None):
        self.terrain_cache_repo = terrain_cache_repo or TerrainCacheRepository()

    def get_terrain_for_route(
        self,
        points: List[Dict],
        bounds: Optional[Dict] = None
    ) -> List[Dict]:
        """Get per-point terrain factors for a route.

        Args:
            points: Route points with 'lat' and 'lon' keys.
            bounds: Optional bounding box {minLat, maxLat, minLon, maxLon}.
                    If not provided, computed from points.

        Returns:
            List of terrain factor dicts, one per point, each with:
            - k_terrain_up, k_terrain_down, k_terrain_flat
            - surface_type (OSM surface tag)
            - category (road/gravel/trail/technical/mud)
        """
        if not points:
            return []

        # Compute bounds if not provided
        if not bounds:
            lats = [p['lat'] for p in points]
            lons = [p['lon'] for p in points]
            bounds = {
                'minLat': min(lats),
                'maxLat': max(lats),
                'minLon': min(lons),
                'maxLon': max(lons),
            }

        # Check cache
        cache_key = self._cache_key(bounds)
        cached_ways = self._get_cached(cache_key)

        if cached_ways is None:
            # Fetch from Overpass
            cached_ways = self._fetch_osm_ways(bounds)
            if cached_ways is not None:
                self._set_cached(cache_key, cached_ways)

        if not cached_ways:
            # Fallback: return defaults for all points
            logger.warning("No OSM data available, using defaults")
            return [DEFAULT_TERRAIN.copy() for _ in points]

        # Match each point to nearest OSM way
        return self._match_points_to_ways(points, cached_ways)

    def get_terrain_summary(self, terrain_factors: List[Dict]) -> Dict:
        """Summarize terrain breakdown for a route.

        Args:
            terrain_factors: Per-point terrain factors from get_terrain_for_route

        Returns:
            Summary dict with category percentages, surface types, and avg factors
        """
        if not terrain_factors:
            return {'error': 'No terrain data'}

        # Count categories
        categories = {}
        surface_types = {}
        total = len(terrain_factors)

        for tf in terrain_factors:
            cat = tf.get('category', 'unknown')
            categories[cat] = categories.get(cat, 0) + 1

            surface = tf.get('surface_type', 'unknown')
            surface_types[surface] = surface_types.get(surface, 0) + 1

        # Average terrain factors
        avg_up = sum(tf.get('k_terrain_up', 1.08) for tf in terrain_factors) / total
        avg_down = sum(tf.get('k_terrain_down', 1.12) for tf in terrain_factors) / total
        avg_flat = sum(tf.get('k_terrain_flat', 1.05) for tf in terrain_factors) / total

        return {
            'category_breakdown': {k: round(v / total * 100, 1) for k, v in sorted(categories.items())},
            'surface_breakdown': {k: round(v / total * 100, 1) for k, v in sorted(surface_types.items())},
            'avg_terrain_factors': {
                'k_terrain_up': round(avg_up, 3),
                'k_terrain_down': round(avg_down, 3),
                'k_terrain_flat': round(avg_flat, 3),
            },
            'total_points': total,
            'has_osm_data': any(tf.get('surface_type', 'unknown') != 'unknown' for tf in terrain_factors),
        }

    def _fetch_osm_ways(self, bounds: Dict) -> Optional[List[Dict]]:
        """Fetch way elements from Overpass API.

        Queries for ways with highway tag (paths, roads, tracks) within bounds.
        Extracts surface, highway, sac_scale, and tracktype tags.

        Args:
            bounds: Bounding box dict

        Returns:
            List of way dicts with geometry and tags, or None on failure
        """
        # Add small buffer to bounds (50m approx)
        buffer = 0.0005  # ~50m at mid latitudes
        south = bounds['minLat'] - buffer
        north = bounds['maxLat'] + buffer
        west = bounds['minLon'] - buffer
        east = bounds['maxLon'] + buffer

        # Overpass QL query: get ways with highway tag and their geometry
        query = f"""
        [out:json][timeout:30];
        way["highway"]({south},{west},{north},{east});
        out body geom;
        """

        try:
            for url in OVERPASS_URLS:
                try:
                    response = requests.post(
                        url,
                        data={"data": query},
                        headers=OVERPASS_HEADERS,
                        timeout=30,
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
                except Exception as e:
                    if url == OVERPASS_URLS[-1]:
                        raise
                    logger.info(f"Overpass {url} failed ({e}), trying next mirror")

            ways = []
            for element in data.get("elements", []):
                if element.get("type") != "way":
                    continue

                tags = element.get("tags", {})
                geometry = element.get("geometry", [])

                if not geometry:
                    continue

                way = {
                    'id': element.get('id'),
                    'tags': {
                        'highway': tags.get('highway', ''),
                        'surface': tags.get('surface', ''),
                        'sac_scale': tags.get('sac_scale', ''),
                        'tracktype': tags.get('tracktype', ''),
                    },
                    'geometry': [(node['lat'], node['lon']) for node in geometry],
                }
                ways.append(way)

            logger.info(f"Fetched {len(ways)} OSM ways for bounds {bounds}")
            return ways

        except Exception as e:
            logger.warning(f"Overpass API query failed: {e}")
            return None

    def _match_points_to_ways(
        self,
        points: List[Dict],
        ways: List[Dict]
    ) -> List[Dict]:
        """Match each route point to its nearest OSM way.

        Uses brute-force nearest-neighbor matching (sufficient for route-sized
        datasets of a few thousand points). For very large datasets, consider
        spatial indexing with Shapely STRtree.

        Args:
            points: Route points with lat/lon
            ways: OSM ways with geometry and tags

        Returns:
            List of terrain factor dicts, one per point
        """
        # Pre-compute way segments for faster matching
        # Each segment is (lat1, lon1, lat2, lon2, way_index)
        segments = []
        for way_idx, way in enumerate(ways):
            geom = way['geometry']
            for j in range(len(geom) - 1):
                segments.append((
                    geom[j][0], geom[j][1],
                    geom[j + 1][0], geom[j + 1][1],
                    way_idx,
                ))

        if not segments:
            return [DEFAULT_TERRAIN.copy() for _ in points]

        results = []
        # Sampling: for efficiency, match every Nth point if route is very long
        # Then interpolate for skipped points
        step = max(1, len(points) // 500)  # At most 500 lookups

        matched_indices = list(range(0, len(points), step))
        matched_results = {}

        for idx in matched_indices:
            p = points[idx]
            plat, plon = p['lat'], p['lon']

            # Find nearest segment
            best_dist = float('inf')
            best_way_idx = -1

            for slat1, slon1, slat2, slon2, widx in segments:
                dist = self._point_to_segment_dist(plat, plon, slat1, slon1, slat2, slon2)
                if dist < best_dist:
                    best_dist = dist
                    best_way_idx = widx

            if best_way_idx >= 0 and best_dist < 0.001:  # ~100m threshold
                way = ways[best_way_idx]
                terrain = self._tags_to_terrain(way['tags'])
            else:
                terrain = DEFAULT_TERRAIN.copy()

            matched_results[idx] = terrain

        # Fill in all points (interpolate from nearest matched)
        for i in range(len(points)):
            if i in matched_results:
                results.append(matched_results[i])
            else:
                # Find nearest matched index
                nearest_idx = min(matched_indices, key=lambda x: abs(x - i))
                results.append(matched_results[nearest_idx])

        return results

    def _tags_to_terrain(self, tags: Dict) -> Dict:
        """Convert OSM tags to terrain factors.

        Priority: surface tag > sac_scale > highway type > default

        Args:
            tags: OSM way tags

        Returns:
            Terrain factor dict
        """
        surface = tags.get('surface', '').lower()
        highway = tags.get('highway', '').lower()
        sac_scale = tags.get('sac_scale', '').lower()

        # Start with surface-based factors
        if surface in SURFACE_FACTORS:
            factors = SURFACE_FACTORS[surface].copy()
            factors['surface_type'] = surface
        elif highway in HIGHWAY_FACTORS:
            factors = HIGHWAY_FACTORS[highway].copy()
            factors['surface_type'] = f"inferred_{highway}"
        else:
            factors = DEFAULT_TERRAIN.copy()

        # Apply SAC scale multiplier if present
        if sac_scale in SAC_SCALE_MULTIPLIERS:
            mult = SAC_SCALE_MULTIPLIERS[sac_scale]
            factors['k_terrain_up'] *= mult
            factors['k_terrain_down'] *= mult
            factors['k_terrain_flat'] *= mult
            factors['sac_scale'] = sac_scale

        return factors

    @staticmethod
    def _point_to_segment_dist(
        plat: float, plon: float,
        slat1: float, slon1: float,
        slat2: float, slon2: float
    ) -> float:
        """Approximate distance from point to line segment (in degrees).

        Uses simple projected distance — adequate for nearby matching.

        Returns:
            Distance in degrees (approximate)
        """
        # Vector from segment start to point
        dx = plon - slon1
        dy = plat - slat1

        # Segment vector
        sx = slon2 - slon1
        sy = slat2 - slat1

        seg_len_sq = sx * sx + sy * sy
        if seg_len_sq < 1e-12:
            # Degenerate segment
            return math.sqrt(dx * dx + dy * dy)

        # Project point onto segment line
        t = max(0.0, min(1.0, (dx * sx + dy * sy) / seg_len_sq))

        # Closest point on segment
        closest_lon = slon1 + t * sx
        closest_lat = slat1 + t * sy

        # Distance
        dlat = plat - closest_lat
        dlon = plon - closest_lon
        return math.sqrt(dlat * dlat + dlon * dlon)

    def _cache_key(self, bounds: Dict) -> str:
        """Generate cache key from bounding box."""
        raw = f"terrain:{bounds['minLat']:.4f}:{bounds['maxLat']:.4f}:{bounds['minLon']:.4f}:{bounds['maxLon']:.4f}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[List[Dict]]:
        """Get cached terrain data if not expired."""
        try:
            return self.terrain_cache_repo.get_cached(key)
        except Exception:
            self.terrain_cache_repo.rollback()
        return None

    def _set_cached(self, key: str, data: List[Dict]):
        """Store terrain data in cache."""
        try:
            expires = datetime.now(timezone.utc) + timedelta(days=TERRAIN_CACHE_TTL_DAYS)
            self.terrain_cache_repo.set_cached(key, data, expires)
            self.terrain_cache_repo.commit()
        except Exception:
            self.terrain_cache_repo.rollback()

    def describe_terrain(self, summary: Dict) -> str:
        """Generate human-readable terrain description for the agent.

        Args:
            summary: Output from get_terrain_summary

        Returns:
            Description string
        """
        breakdown = summary.get('category_breakdown', {})
        factors = summary.get('avg_terrain_factors', {})

        parts = []
        for cat in ['road', 'gravel', 'trail', 'technical', 'mud']:
            pct = breakdown.get(cat, 0)
            if pct > 0:
                parts.append(f"{pct:.0f}% {cat}")

        unknown = breakdown.get('unknown', 0)
        if unknown > 50:
            parts.append(f"{unknown:.0f}% unmapped")

        terrain_desc = ", ".join(parts) if parts else "No terrain data available"

        avg_penalty = ((factors.get('k_terrain_up', 1.0) + factors.get('k_terrain_down', 1.0)) / 2.0 - 1.0) * 100

        if avg_penalty > 15:
            difficulty = "Very technical terrain"
        elif avg_penalty > 10:
            difficulty = "Technical terrain"
        elif avg_penalty > 5:
            difficulty = "Moderate trail"
        elif avg_penalty > 2:
            difficulty = "Easy trail/gravel"
        else:
            difficulty = "Road/paved"

        return f"{difficulty}: {terrain_desc}. Average terrain penalty: ~{avg_penalty:.0f}%."

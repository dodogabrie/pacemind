"""Race calendar lookup service.

Finds candidate B/C tune-up races near a user's training base that can
substitute a peak long run when the user's max_long_run_km is below the
A-race-derived target.

Architecture:
- Public entry point: find_races(lat, lon, radius_km, target_distance_km, ...)
- Pluggable providers (ITRA, FIDAL) gated by env-var credentials
- Distance / elevation / location / date scoring → ranked list
- Best-effort: any provider failure degrades to an empty list rather than
  blowing up the agent flow. The handler falls back to "raise cap" /
  "accept compromise" when this returns no candidates.

Credentials:
  FIDAL_ENABLED — set to '1' to enable FIDAL HTML scrape (stub, not implemented)

Note on ITRA: there is no public ITRA API. The race calendar at
https://itra.run/Races/RaceCalendar is a SPA that hydrates client-side and
does not expose an obvious JSON endpoint. Any "ITRA provider" here would be
either a fragile HTML scrape behind Cloudflare or a Playwright headless
session — both deliberately out of scope until we capture a real network
trace and decide on an approach. See ``_provider_itra`` for status.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Scoring weights (sum to 1.0)
W_DISTANCE = 0.40
W_ELEV = 0.20
W_DISTANCE_FROM_BASE = 0.15
W_SURFACE = 0.15
W_TYPE = 0.10

DEFAULT_RADIUS_KM = 100.0
HTTP_TIMEOUT = 8


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_races(
    *,
    lat: float,
    lon: float,
    radius_km: float = DEFAULT_RADIUS_KM,
    target_distance_km: float,
    target_elev_m: Optional[float] = None,
    window_start: str,
    window_end: str,
    country: Optional[str] = None,
    target_surface: Optional[str] = None,
    target_race_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search providers and return ranked race candidates.

    Returns a list of dicts with keys:
      name, date (YYYY-MM-DD), location, country, distance_km, elev_m,
      url, lat, lon, distance_from_base_km, fit_score (0-1).
    """
    try:
        start_d = datetime.strptime(window_start, '%Y-%m-%d').date()
        end_d = datetime.strptime(window_end, '%Y-%m-%d').date()
    except ValueError as e:
        logger.warning(f"find_races: bad date window: {e}")
        return []

    if not country:
        country = _reverse_geocode_country(lat, lon)

    candidates: List[Dict[str, Any]] = []

    # Primary source: curated DB (always tried, never fails)
    try:
        candidates.extend(_provider_db(
            lat=lat, lon=lon, radius_km=radius_km, country=country,
            start_date=start_d, end_date=end_d,
        ))
    except Exception as e:
        logger.warning(f"db race provider failed: {e}")

    # Optional augment: external providers
    for provider in _enabled_providers():
        try:
            candidates.extend(provider(
                lat=lat, lon=lon, radius_km=radius_km, country=country,
                start_date=start_d, end_date=end_d,
            ))
        except Exception as e:
            logger.warning(f"race provider {provider.__name__} failed: {e}")

    candidates = _dedupe_candidates(candidates)

    # Filter out races outside the date window or radius (defensive — providers
    # should already filter, but they often over-return).
    filtered: List[Dict[str, Any]] = []
    for r in candidates:
        try:
            r_date = datetime.strptime(r['date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            continue
        if r_date < start_d or r_date > end_d:
            continue
        d_km = _haversine_km(lat, lon, r.get('lat'), r.get('lon'))
        if d_km is None or d_km > radius_km:
            continue
        r['distance_from_base_km'] = round(d_km, 1)
        r['fit_score'] = _score_race(
            r,
            target_distance_km=target_distance_km,
            target_elev_m=target_elev_m,
            radius_km=radius_km,
            target_surface=target_surface,
            target_race_type=target_race_type,
        )
        filtered.append(r)

    filtered.sort(key=lambda x: x['fit_score'], reverse=True)
    return filtered


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def _enabled_providers():
    providers = []
    if os.getenv('FIDAL_ENABLED') == '1':
        providers.append(_provider_fidal)
    return providers


def _provider_db(*, lat, lon, radius_km, country, start_date, end_date) -> List[Dict[str, Any]]:
    """Curated races persisted in the public ``races`` table.

    The bounding-box prefilter in the repo is generous; the haversine +
    ``fit_score`` step in ``find_races`` then trims to the real radius.
    """
    from repositories.race_repository import RaceRepository
    repo = RaceRepository()
    rows = repo.search(
        start_date=start_date,
        end_date=end_date,
        country=country,
        near_lat=lat,
        near_lon=lon,
        max_travel_km=radius_km,
        limit=100,
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        out.append({
            'source': r.source,
            'race_id': r.id,
            'name': r.name,
            'date': r.date.isoformat(),
            'location': r.location or '',
            'country': r.country or country or '',
            'distance_km': float(r.distance_km),
            'elev_m': float(r.elev_gain_m or 0),
            'lat': float(r.lat),
            'lon': float(r.lon),
            'url': r.url or '',
            'surface': r.surface or None,
            'race_type': r.race_type or None,
        })
    return out


def _dedupe_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicates that hit from multiple providers.

    Two races collide when they share (name lowercased, date). The DB row
    wins because it carries the persisted ``race_id`` link.
    """
    seen: Dict[tuple, Dict[str, Any]] = {}
    for r in candidates:
        key = (str(r.get('name', '')).strip().lower(), r.get('date'))
        prev = seen.get(key)
        if prev is None:
            seen[key] = r
            continue
        # Prefer the entry that already carries a race_id (DB-backed).
        if 'race_id' in r and 'race_id' not in prev:
            seen[key] = r
    return list(seen.values())


def _provider_itra(*, lat, lon, radius_km, country, start_date, end_date) -> List[Dict[str, Any]]:
    """ITRA race calendar provider — NOT IMPLEMENTED.

    https://itra.run/Races/RaceCalendar is a client-side-rendered SPA. The
    page hydrates from JS state and does not expose an obvious JSON endpoint
    in DevTools (verified 2026-04). There is no public/free ITRA API.

    Realistic options when we decide to revisit:
      1. Capture a real network trace while submitting the search form, then
         replay the discovered XHR with session cookie + UA.
      2. Headless Playwright: load the page, fill filters, intercept the
         hydration response, dump JSON. Slow but robust to JS rendering.
      3. Use DUV (statistik.d-u-v.org) or utmb.world as substitutes for
         international ultra coverage.

    Until then this is an explicit no-op so callers don't trust a stub.
    """
    return []


def _provider_fidal(*, lat, lon, radius_km, country, start_date, end_date) -> List[Dict[str, Any]]:
    """FIDAL (Italian Athletics Federation) calendar provider.

    Scrapes https://www.fidal.it/calendario.php. Italian races only — only
    enable when country == 'IT'. Implementation is best-effort; FIDAL doesn't
    publish lat/lon, so the provider geocodes the city via ORS in a follow-up
    pass. For v1 we return [] if scraping is not configured to avoid shipping
    a flaky scraper. Set FIDAL_ENABLED=1 to opt in.
    """
    if country and country.upper() != 'IT':
        return []
    # TODO: implement FIDAL HTML scrape + per-race city geocoding via ORS.
    # See https://www.fidal.it/calendario.php?year=YYYY&month=MM
    return []


# ---------------------------------------------------------------------------
# Scoring & geometry
# ---------------------------------------------------------------------------

_SURFACE_RELATED = {
    frozenset({'trail', 'mountain'}): 0.7,
    frozenset({'trail', 'mixed'}): 0.7,
    frozenset({'road', 'track'}): 0.7,
    frozenset({'road', 'mixed'}): 0.5,
}

_TYPE_RELATED = {
    frozenset({'trail', 'ultra'}): 0.6,
    frozenset({'marathon', 'ultra'}): 0.5,
    frozenset({'marathon', 'road'}): 0.7,
}


def _category_score(target: Optional[str], actual: Optional[str], related: Dict) -> float:
    """Match score for a free-form category field (surface, race_type).

    Unknown on either side → 0.5 (neutral, doesn't penalise sparse data).
    Exact case-insensitive match → 1.0.
    Pair listed in ``related`` → that table's score.
    Else → 0.2 (mismatch, but not a hard zero — taxonomies overlap).
    """
    if not target or not actual:
        return 0.5
    t = target.strip().lower()
    a = actual.strip().lower()
    if t == a:
        return 1.0
    return related.get(frozenset({t, a}), 0.2)


def _score_race(
    race,
    *,
    target_distance_km,
    target_elev_m,
    radius_km,
    target_surface: Optional[str] = None,
    target_race_type: Optional[str] = None,
) -> float:
    """Combined fit score in [0, 1]. Higher is better."""
    # Distance fit: 1.0 within ±15%, drops to 0 by ±50%
    d_err = abs(race.get('distance_km', 0) - target_distance_km) / max(target_distance_km, 1)
    d_score = max(0.0, 1.0 - max(0.0, (d_err - 0.15)) / 0.35)

    # Elevation fit: 1.0 within ±25%, drops to 0 by ±75% (only if target given)
    if target_elev_m and target_elev_m > 0:
        e_err = abs(race.get('elev_m', 0) - target_elev_m) / target_elev_m
        e_score = max(0.0, 1.0 - max(0.0, (e_err - 0.25)) / 0.50)
    else:
        e_score = 0.5  # neutral

    # Proximity: closer is better, linear 1.0 at 0km → 0 at radius_km
    prox_score = max(0.0, 1.0 - race['distance_from_base_km'] / max(radius_km, 1))

    surface_score = _category_score(target_surface, race.get('surface'), _SURFACE_RELATED)
    type_score = _category_score(target_race_type, race.get('race_type'), _TYPE_RELATED)

    return round(
        W_DISTANCE * d_score
        + W_ELEV * e_score
        + W_DISTANCE_FROM_BASE * prox_score
        + W_SURFACE * surface_score
        + W_TYPE * type_score,
        3,
    )


def _haversine_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _reverse_geocode_country(lat: float, lon: float) -> Optional[str]:
    """Reverse-geocode lat/lon → ISO-2 country code via ORS Pelias.

    Reuses the ORS_API_KEY already used by route_generation_service. Returns
    None on any failure; the caller treats None as "no country filter".
    """
    api_key = os.getenv('ORS_API_KEY')
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.openrouteservice.org/geocode/reverse",
            params={
                'api_key': api_key,
                'point.lat': lat,
                'point.lon': lon,
                'size': 1,
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        feats = resp.json().get('features', [])
        if not feats:
            return None
        props = feats[0].get('properties', {})
        cc = props.get('country_a') or props.get('country_code')
        if cc and len(cc) >= 2:
            return cc[:2].upper()
    except Exception as e:
        logger.warning(f"ORS reverse geocode failed: {e}")
    return None

"""Forward-geocode ``races`` rows that are missing lat/lon.

Uses ORS Pelias (the same ``ORS_API_KEY`` already configured for route
generation). Free tier is 1000 req/day, 40 req/min — we sleep 1.6s between
calls to stay under the rate limit with margin.

Idempotent: only touches rows where ``lat IS NULL OR lon IS NULL``. Re-run
safely after each scraper pass.

Usage:
    docker exec gpx_analyzer-backend-1 python scripts/geocode_races.py
    docker exec gpx_analyzer-backend-1 python scripts/geocode_races.py --limit 50
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import or_

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from models import Race  # noqa: E402

ORS_URL = "https://api.openrouteservice.org/geocode/search"
RATE_LIMIT_SLEEP = 1.6  # seconds between requests (≈ 37/min, under the 40/min cap)
HTTP_TIMEOUT = 10


def geocode(api_key: str, query: str, country: str | None) -> tuple[float, float] | None:
    params = {"api_key": api_key, "text": query, "size": 1}
    if country:
        params["boundary.country"] = country
    try:
        resp = requests.get(ORS_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
    except Exception as e:
        print(f"  ! request failed for '{query}': {e}", file=sys.stderr)
        return None
    if not feats:
        return None
    coords = feats[0].get("geometry", {}).get("coordinates")
    if not coords or len(coords) < 2:
        return None
    lon, lat = float(coords[0]), float(coords[1])
    return lat, lon


def run(limit: int | None) -> int:
    api_key = os.getenv("ORS_API_KEY")
    if not api_key:
        print("ORS_API_KEY not set", file=sys.stderr)
        return 1

    q = Race.query.filter(or_(Race.lat.is_(None), Race.lon.is_(None)))
    q = q.order_by(Race.id.asc())
    if limit:
        q = q.limit(limit)
    rows = q.all()

    if not rows:
        print("No races need geocoding.")
        return 0

    print(f"Geocoding {len(rows)} races (~{len(rows) * RATE_LIMIT_SLEEP / 60:.1f} min)")
    hits = misses = 0
    for i, race in enumerate(rows, 1):
        query_text = race.location or race.name
        if not query_text:
            misses += 1
            continue
        country = (race.country or "").upper() or None
        result = geocode(api_key, query_text, country)
        if result is None:
            print(f"  [{i}/{len(rows)}] miss: {query_text}")
            misses += 1
        else:
            race.lat, race.lon = result
            hits += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(rows)}] hit: {query_text} -> {race.lat:.4f},{race.lon:.4f}")
                db.session.commit()  # periodic flush
        time.sleep(RATE_LIMIT_SLEEP)

    db.session.commit()
    print(f"Done. hits={hits} misses={misses}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="Cap rows processed (debug)")
    args = p.parse_args()
    app = create_app()
    with app.app_context():
        return run(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())

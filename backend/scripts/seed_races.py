"""Seed the races table from a curated CSV.

Idempotent: re-running upserts on (source, external_id).

Usage:
    cd backend
    source venv/bin/activate
    python scripts/seed_races.py [path/to/races.csv]

The default CSV lives at backend/data/races_seed.csv.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Make the backend package importable when run directly.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from models import Race  # noqa: E402
from services.race_taxonomy import normalise_race_type  # noqa: E402


DEFAULT_SOURCE = 'seed'

# URLs that point to a scraper's calendar/listing page rather than an
# event's official website. Stored as `url` in the CSV by mistake, but
# surfaced as "Official site" in the UI — so we drop them on ingest.
SCRAPER_LISTING_URLS = {
    'https://www.sterratogang.it/calendario-gare-trailrunning/',
}


def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.strip() in SCRAPER_LISTING_URLS:
        return None
    return url


def _slugify(value: str) -> str:
    out = []
    prev_dash = False
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append('-')
            prev_dash = True
    return ''.join(out).strip('-')


def _parse_float(v: str) -> float | None:
    if v is None or v == '':
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_int(v: str) -> int | None:
    if v is None or v == '':
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _row_to_attrs(row: Dict[str, str]) -> Dict[str, Any]:
    source = (row.get('source') or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE
    distance_km = float(row['distance_km'])
    surface = row.get('surface') or None
    return {
        'source': source,
        'external_id': row['external_id'],
        'name': row['name'],
        'slug': _slugify(f"{source}-{row['external_id']}"),
        'url': _clean_url(row.get('url')),
        'description': row.get('description') or None,
        'date': datetime.strptime(row['date'], '%Y-%m-%d').date(),
        'country': (row.get('country') or '').upper() or None,
        'region': row.get('region') or None,
        'location': row.get('location') or None,
        'lat': _parse_float(row.get('lat', '')),
        'lon': _parse_float(row.get('lon', '')),
        'distance_km': distance_km,
        'elev_gain_m': _parse_float(row.get('elev_gain_m', '')),
        'elev_loss_m': _parse_float(row.get('elev_loss_m', '')),
        'surface': surface,
        # CSVs produced by scrape_utmb.py may still carry raw World Series
        # distance bands; keep the column on the canonical taxonomy.
        'race_type': normalise_race_type(
            row.get('race_type'), distance_km, surface
        ),
        'itra_points': _parse_int(row.get('itra_points', '')),
    }


def seed(csv_path: Path) -> Dict[str, int]:
    inserted = 0
    updated = 0
    with csv_path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            attrs = _row_to_attrs(row)
            existing = Race.query.filter_by(
                source=attrs['source'],
                external_id=attrs['external_id'],
            ).first()
            if existing:
                for k, v in attrs.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.session.add(Race(**attrs))
                inserted += 1
    db.session.commit()
    return {'inserted': inserted, 'updated': updated}


def main() -> int:
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = BACKEND_ROOT / 'data' / 'races_seed.csv'
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    app = create_app()
    with app.app_context():
        result = seed(csv_path)
    print(f"Races seeded: inserted={result['inserted']} updated={result['updated']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

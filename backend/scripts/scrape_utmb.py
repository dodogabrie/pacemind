"""Scrape the UTMB World Series races into a CSV.

Two-phase scrape:

1. **Index** — fetch ``https://utmb.world/utmb-world-series-events`` once,
   parse ``__NEXT_DATA__`` → list of ~65 events (one per venue/weekend).
   Each event ships ``latitude``, ``longitude``, ``country``, ``tenant``.

2. **Detail** — for each event with a ``tenant``, fetch the tenant
   subdomain root (e.g. ``https://mrww.utmb.world/``) and extract its
   ``listOfRaces`` slice. That slice carries the *actual* per-race
   ``distance`` (km), ``elevationGain`` (m), full name, slug, band code.

We emit one CSV row per (tenant, race-slug). Per-race detail is preferred;
if a tenant fetch fails we fall back to band-based rows derived from the
event's ``raceCategories`` so an outage on one subdomain doesn't poison
the whole batch.

UTMB ships lat/lon at the event level only — multiple races at the same
venue inherit the venue coordinates. Good enough for "near me" search.

Usage:
    docker compose exec backend python scripts/scrape_utmb.py
    docker compose exec backend python scripts/seed_races.py data/utmb_world_series.csv
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

INDEX_URL = "https://utmb.world/utmb-world-series-events"
USER_AGENT = "Mozilla/5.0 (compatible; PaceMindBot/1.0; +https://pacemind.app)"
TENANT_SLEEP_SEC = 1.5
HTTP_TIMEOUT = 30
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = BACKEND_ROOT / "data" / "utmb_world_series.csv"

# Make the backend package importable when run directly (same pattern as
# scripts/seed_races.py).
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.race_taxonomy import normalise_race_type  # noqa: E402

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

# "17th July 2026" → date. UTMB's tenant pages humanise dates with English
# ordinal suffixes; the index page already has ISO ``dateBegin`` so this
# only matters for the detail phase.
ORDINAL_DATE_RE = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})\s*$", re.IGNORECASE)
DATE_RANGE_RE = re.compile(r"^\s*(\d{1,2})(?:st|nd|rd|th)?\s*-\s*\d.*?(\w+)\s+(\d{4})\s*$", re.IGNORECASE)

# Fallback band → nominal km when tenant fetch fails. These are deliberately
# coarse; the detail phase replaces them with real numbers.
CATEGORY_KM = {
    'ws20KM': 20.0,
    'ws50KM': 50.0,
    'ws100KM': 100.0,
    'ws50M': 80.0,
    'ws100M': 161.0,
}

_NAME_TO_ISO2 = {
    'France': 'FR', 'Italy': 'IT', 'Switzerland': 'CH', 'Spain': 'ES',
    'United Kingdom': 'GB', 'Portugal': 'PT', 'Germany': 'DE', 'Austria': 'AT',
    'Andorra': 'AD', 'Norway': 'NO', 'Sweden': 'SE', 'Iceland': 'IS',
    'Slovenia': 'SI', 'Croatia': 'HR', 'Greece': 'GR', 'Turkey': 'TR',
    'Poland': 'PL', 'Czech Republic': 'CZ', 'Hungary': 'HU', 'Romania': 'RO',
    'United States': 'US', 'Canada': 'CA', 'Mexico': 'MX',
    'Brazil': 'BR', 'Argentina': 'AR', 'Chile': 'CL', 'Peru': 'PE',
    'Australia': 'AU', 'New Zealand': 'NZ',
    'Japan': 'JP', 'China': 'CN', 'South Korea': 'KR', 'Thailand': 'TH',
    'India': 'IN', 'Indonesia': 'ID', 'Philippines': 'PH', 'Vietnam': 'VN',
    'Nepal': 'NP', 'Hong Kong': 'HK', 'Taiwan': 'TW', 'Malaysia': 'MY',
    'South Africa': 'ZA', 'Morocco': 'MA', 'Kenya': 'KE',
    'United Arab Emirates': 'AE', 'Saudi Arabia': 'SA', 'Oman': 'OM',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _country_iso2(event: dict) -> str:
    code = (event.get('countryCode') or '').strip().upper()
    if len(code) == 2:
        return code
    name = (event.get('country') or '').strip()
    return _NAME_TO_ISO2.get(name, '')


def _parse_human_date(s: str | None, fallback_iso: str) -> str:
    """Tenant ``startDate`` is humanised. Return ISO date, or fall back to
    the event's ISO ``dateBegin`` if parsing fails (still useful — the race
    is at most a few days off the event start)."""
    if not s:
        return fallback_iso
    s = s.strip()
    m = ORDINAL_DATE_RE.match(s) or DATE_RANGE_RE.match(s)
    if not m:
        return fallback_iso
    day, month_name, year = m.groups()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(f"{day} {month_name} {year}", fmt).date().isoformat()
        except ValueError:
            continue
    return fallback_iso


def _stat_value(stats: list, name: str):
    """Pick a value out of a UTMB ``statsUp``/``statsDown`` list of
    ``{name, value, postfix}`` dicts."""
    for s in stats or []:
        if s.get('name') == name:
            return s.get('value')
    return None


def _extract_next_data(html_text: str) -> dict:
    m = NEXT_DATA_RE.search(html_text)
    if not m:
        raise RuntimeError("__NEXT_DATA__ blob not found")
    return json.loads(m.group(1))


def _find_slice(slices: list, slice_type: str) -> dict | None:
    for sl in slices:
        if sl.get('type') == slice_type or sl.get('slice_type') == slice_type:
            return sl
    return None


# ---------------------------------------------------------------------------
# Phase 1: index
# ---------------------------------------------------------------------------

def fetch_events() -> list[dict]:
    print(f"Fetching index {INDEX_URL}", file=sys.stderr)
    resp = requests.get(INDEX_URL, headers={'User-Agent': USER_AGENT}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = _extract_next_data(resp.text)
    slices = data.get('props', {}).get('pageProps', {}).get('slices', [])
    for sl in slices:
        events = sl.get('data', {}).get('events')
        if isinstance(events, list) and events:
            return events
    raise RuntimeError("events list not found in index __NEXT_DATA__")


# ---------------------------------------------------------------------------
# Phase 2: per-tenant detail
# ---------------------------------------------------------------------------

def fetch_tenant_races(tenant_url: str) -> list[dict]:
    """Return the ``listOfRaces`` array for a tenant, or [] on any failure."""
    if not tenant_url:
        return []
    if not tenant_url.endswith('/'):
        tenant_url = tenant_url + '/'
    try:
        resp = requests.get(tenant_url, headers={'User-Agent': USER_AGENT}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = _extract_next_data(resp.text)
    except Exception as e:
        logger.warning("tenant fetch failed for %s: %s", tenant_url, e)
        return []

    slices = data.get('props', {}).get('pageProps', {}).get('slices', [])
    sl = _find_slice(slices, 'listOfRaces')
    if not sl:
        logger.warning("listOfRaces slice not found for %s", tenant_url)
        return []
    return sl.get('data', {}).get('races', []) or []


def _row_from_detail(event: dict, race: dict) -> dict | None:
    """Build a CSV row from a tenant ``listOfRaces`` race entry."""
    slug = (race.get('slug') or '').strip()
    if not slug:
        return None
    distance = _stat_value(race.get('details', {}).get('statsDown'), 'distance')
    if distance is None:
        return None  # no comparable distance → drop
    elev = _stat_value(race.get('details', {}).get('statsDown'), 'elevationGain') or ''
    band = _stat_value(race.get('details', {}).get('statsUp'), 'categoryWorldSeries') or ''
    tenant = (event.get('tenant') or '').strip()

    return {
        'source': 'utmb',
        'external_id': f"{tenant}-{slug}" if tenant else slug,
        'name': race.get('name') or race.get('shortName') or slug,
        'date': _parse_human_date(race.get('startDate'), (event.get('dateBegin') or '')[:10]),
        'country': _country_iso2(event),
        'region': event.get('continent') or '',
        'location': race.get('startLocation') or event.get('placeName') or '',
        'lat': event.get('latitude') if event.get('latitude') is not None else '',
        'lon': event.get('longitude') if event.get('longitude') is not None else '',
        'distance_km': float(distance),
        'elev_gain_m': float(elev) if elev != '' else '',
        'elev_loss_m': '',
        'surface': 'trail',
        # `band` is a UTMB World Series *distance band* (ws50KM, ws100M, ...),
        # not a race type. Map it onto the canonical taxonomy using the real
        # distance we just parsed. See services/race_taxonomy.py.
        'race_type': normalise_race_type(band, float(distance), 'trail') or 'trail',
        'itra_points': '',
        'url': event.get('url') or '',
        'description': '',
    }


def _row_from_band(event: dict, band: str) -> dict | None:
    """Fallback row when tenant detail is unavailable. Distance is the
    band's nominal km; the seed CSV can override per flagship race."""
    dist = CATEGORY_KM.get(band)
    if dist is None:
        return None
    tenant = (event.get('tenant') or '').strip()
    date_iso = (event.get('dateBegin') or '')[:10]
    if not tenant or not date_iso:
        return None
    return {
        'source': 'utmb',
        'external_id': f"{tenant}-{date_iso}-{band}",
        'name': f"{event.get('title') or tenant} ({band[2:]})",
        'date': date_iso,
        'country': _country_iso2(event),
        'region': event.get('continent') or '',
        'location': event.get('placeName') or '',
        'lat': event.get('latitude') if event.get('latitude') is not None else '',
        'lon': event.get('longitude') if event.get('longitude') is not None else '',
        'distance_km': dist,
        'elev_gain_m': '',
        'elev_loss_m': '',
        'surface': 'trail',
        # Nominal band distance only; `external_id` above keeps the raw band
        # because it is an identity and changing it would duplicate rows.
        'race_type': normalise_race_type(band, dist, 'trail'),
        'itra_points': '',
        'url': event.get('url') or '',
        'description': '',
    }


def expand(events: list[dict], *, fetch_detail: bool = True) -> Iterable[dict]:
    """Yield one row per race. If ``fetch_detail``, hit each tenant for
    real distance/elev; otherwise emit band-fallback rows only."""
    seen: set[str] = set()
    for i, ev in enumerate(events, 1):
        tenant_url = (ev.get('url') or '').strip()
        rows: list[dict] = []

        if fetch_detail and tenant_url:
            print(f"  [{i}/{len(events)}] {tenant_url}", file=sys.stderr)
            for race in fetch_tenant_races(tenant_url):
                row = _row_from_detail(ev, race)
                if row:
                    rows.append(row)
            time.sleep(TENANT_SLEEP_SEC)

        if not rows:
            # Either detail fetch is disabled, the tenant fetch returned
            # nothing, or every race lacked a usable distance. Fall back to
            # band-derived rows so the event isn't lost entirely.
            for band in ev.get('raceCategories') or []:
                row = _row_from_band(ev, band)
                if row:
                    rows.append(row)

        for row in rows:
            ext = row['external_id']
            if ext in seen:
                continue
            seen.add(ext)
            yield row


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    events = fetch_events()
    rows = list(expand(events, fetch_detail=True))
    if not rows:
        print("No races emitted.", file=sys.stderr)
        return 1

    fieldnames = list(rows[0].keys())
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} races from {len(events)} events -> {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

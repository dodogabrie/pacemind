"""Scrape the DUV ultra-marathon calendar into a CSV.

Source: https://statistik.d-u-v.org/calendar.php — server-rendered HTML
table, no JS, no Cloudflare. Each calendar year holds ~5–7k events
paginated 1000/page. We walk pages until empty.

Each row in the source table:

    <tr class='odd|even'>
      <td>DD.MM.YYYY</td>
      <td><a href='eventdetail.php?event=ID'>Name</a></td>
      <td>50km | 100mi | 24h | 230km/6stages</td>
      <td>City, Region (ISO-3 country)</td>
      <td>Status</td>
      <td>IAU-Label</td>
      <td>Results</td>
    </tr>

DUV ships no lat/lon — `geocode_races.py` fills them on a follow-up pass.
Time-based events (``24h``, ``12h`` …) have no comparable distance, so we
skip them; they won't help an agent searching for a 50 km tune-up. Distance
ranges/stage races (``230km/6stages``) keep the leading km value.

DUV uses IOC-style 3-letter country codes (GER, SUI, NED…) which differ
from ISO-3166 alpha-3. ``_ISO3_TO_ISO2`` translates them to the 2-letter
codes the ``races`` table stores.

Output CSV is the schema consumed by ``seed_races.py``:

    docker compose exec backend python scripts/scrape_duv.py            # current year
    docker compose exec backend python scripts/scrape_duv.py --year 2026
    docker compose exec backend python scripts/seed_races.py data/duv_2026.csv
    docker compose exec backend python scripts/geocode_races.py
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import logging
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import requests

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://statistik.d-u-v.org/calendar.php"
USER_AGENT = "Mozilla/5.0 (compatible; PaceMindBot/1.0; +https://pacemind.app)"
PAGE_SLEEP_SEC = 1.5  # be polite — the calendar is one of their busier pages
PAGE_SIZE = 1000  # DUV's fixed page size; verified empirically on 2026 calendar

ROW_RE = re.compile(r"<tr class='(?:odd|even)'>(.*?)</tr>", re.DOTALL)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
LINK_RE = re.compile(r"href='eventdetail\.php\?event=(\d+)'[^>]*>([^<]+)</a>")
COUNTRY_RE = re.compile(r"\(([A-Z]{3})\)\s*$")
KM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*km", re.IGNORECASE)
MI_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mi", re.IGNORECASE)
HOURS_ONLY_RE = re.compile(r"^\s*\d+\s*[hH]\s*$")
TAG_RE = re.compile(r"<[^>]+>")
TOTAL_RE = re.compile(r"(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+search results?", re.IGNORECASE)

# IOC / DUV-style 3-letter codes → ISO-3166-1 alpha-2. Covers the IOC table
# plus common DUV-specific divergences. Missing codes log a warning and the
# row is still emitted with empty country (geocode_races.py geocodes without
# a country bound — slightly less precise but never lossy).
_ISO3_TO_ISO2 = {
    'AFG': 'AF', 'ALB': 'AL', 'ALG': 'DZ', 'AND': 'AD', 'ANG': 'AO', 'ANT': 'AG',
    'ARG': 'AR', 'ARM': 'AM', 'ARU': 'AW', 'ASA': 'AS', 'ATA': 'AQ', 'AUS': 'AU',
    'AUT': 'AT', 'AZE': 'AZ', 'BAH': 'BS', 'BAN': 'BD', 'BAR': 'BB', 'BDI': 'BI',
    'BEL': 'BE', 'BEN': 'BJ', 'BER': 'BM', 'BHU': 'BT', 'BIH': 'BA', 'BIZ': 'BZ',
    'BLR': 'BY', 'BOL': 'BO', 'BOT': 'BW', 'BRA': 'BR', 'BRN': 'BH', 'BRU': 'BN',
    'BUL': 'BG', 'BUR': 'BF', 'CAF': 'CF', 'CAM': 'KH', 'CAN': 'CA', 'CAY': 'KY',
    'CGO': 'CG', 'CHA': 'TD', 'CHI': 'CL', 'CHN': 'CN', 'CIV': 'CI', 'CMR': 'CM',
    'COD': 'CD', 'COK': 'CK', 'COL': 'CO', 'COM': 'KM', 'CPV': 'CV', 'CRC': 'CR',
    'CRO': 'HR', 'CUB': 'CU', 'CYP': 'CY', 'CZE': 'CZ', 'DEN': 'DK', 'DJI': 'DJ',
    'DMA': 'DM', 'DOM': 'DO', 'ECU': 'EC', 'EGY': 'EG', 'ERI': 'ER', 'ESA': 'SV',
    'ESP': 'ES', 'EST': 'EE', 'ETH': 'ET', 'FIJ': 'FJ', 'FIN': 'FI', 'FRA': 'FR',
    'FSM': 'FM', 'GAB': 'GA', 'GAM': 'GM', 'GBR': 'GB', 'GBS': 'GW', 'GEO': 'GE',
    'GEQ': 'GQ', 'GER': 'DE', 'GHA': 'GH', 'GRE': 'GR', 'GRN': 'GD', 'GUA': 'GT',
    'GUI': 'GN', 'GUM': 'GU', 'GUY': 'GY', 'HAI': 'HT', 'HKG': 'HK', 'HON': 'HN',
    'HUN': 'HU', 'INA': 'ID', 'IND': 'IN', 'IRI': 'IR', 'IRL': 'IE', 'IRQ': 'IQ',
    'ISL': 'IS', 'ISR': 'IL', 'ISV': 'VI', 'ITA': 'IT', 'IVB': 'VG', 'JAM': 'JM',
    'JOR': 'JO', 'JPN': 'JP', 'KAZ': 'KZ', 'KEN': 'KE', 'KGZ': 'KG', 'KIR': 'KI',
    'KOR': 'KR', 'KOS': 'XK', 'KSA': 'SA', 'KUW': 'KW', 'LAO': 'LA', 'LAT': 'LV',
    'LBA': 'LY', 'LBN': 'LB', 'LBR': 'LR', 'LCA': 'LC', 'LES': 'LS', 'LIE': 'LI',
    'LTU': 'LT', 'LUX': 'LU', 'MAD': 'MG', 'MAR': 'MA', 'MAS': 'MY', 'MAW': 'MW',
    'MDA': 'MD', 'MDV': 'MV', 'MEX': 'MX', 'MGL': 'MN', 'MHL': 'MH', 'MKD': 'MK',
    'MLI': 'ML', 'MLT': 'MT', 'MNE': 'ME', 'MON': 'MC', 'MOZ': 'MZ', 'MRI': 'MU',
    'MTN': 'MR', 'MYA': 'MM', 'NAM': 'NA', 'NCA': 'NI', 'NED': 'NL', 'NEP': 'NP',
    'NGR': 'NG', 'NIG': 'NE', 'NOR': 'NO', 'NRU': 'NR', 'NZL': 'NZ', 'OMA': 'OM',
    'PAK': 'PK', 'PAN': 'PA', 'PAR': 'PY', 'PER': 'PE', 'PHI': 'PH', 'PLE': 'PS',
    'PLW': 'PW', 'PNG': 'PG', 'POL': 'PL', 'POR': 'PT', 'PRK': 'KP', 'PUR': 'PR',
    'QAT': 'QA', 'ROU': 'RO', 'RSA': 'ZA', 'RUS': 'RU', 'RWA': 'RW', 'SAM': 'WS',
    'SEN': 'SN', 'SEY': 'SC', 'SGP': 'SG', 'SKN': 'KN', 'SLE': 'SL', 'SLO': 'SI',
    'SMR': 'SM', 'SOL': 'SB', 'SOM': 'SO', 'SRB': 'RS', 'SRI': 'LK', 'STP': 'ST',
    'SUD': 'SD', 'SUI': 'CH', 'SUR': 'SR', 'SVK': 'SK', 'SVN': 'SI', 'SWE': 'SE',
    'SWZ': 'SZ', 'SYR': 'SY', 'TAN': 'TZ', 'TGA': 'TO', 'THA': 'TH', 'TJK': 'TJ',
    'TKM': 'TM', 'TLS': 'TL', 'TOG': 'TG', 'TPE': 'TW', 'TRI': 'TT', 'TUN': 'TN',
    'TUR': 'TR', 'TUV': 'TV', 'UAE': 'AE', 'UGA': 'UG', 'UKR': 'UA', 'URU': 'UY',
    'USA': 'US', 'UZB': 'UZ', 'VAN': 'VU', 'VEN': 'VE', 'VIE': 'VN', 'VIN': 'VC',
    'YEM': 'YE', 'ZAM': 'ZM', 'ZIM': 'ZW',
}

# Codes already warned about — keep noise down across pages.
_unmapped_seen: set[str] = set()


def _strip(s: str) -> str:
    return html.unescape(TAG_RE.sub('', s)).strip()


def _parse_date(raw: str) -> str | None:
    parts = raw.strip().split('.')
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def _parse_distance_km(raw: str) -> float | None:
    """Return the headline distance in km, or None for time-based events.

    Stage races / ranges (``230km/6stages``) keep the leading km value, which
    is what runners compare against a target distance.
    """
    if HOURS_ONLY_RE.match(raw):
        return None
    km = KM_RE.search(raw)
    if km:
        return float(km.group(1))
    mi = MI_RE.search(raw)
    if mi:
        return round(float(mi.group(1)) * 1.609344, 1)
    return None


def _classify(distance_km: float) -> str:
    return 'ultra' if distance_km >= 50 else 'trail'


def _split_venue(venue: str) -> tuple[str, str | None]:
    """``Falls Creek, VIC (AUS)`` → (location, ISO-2 country or None).

    Unmapped 3-letter codes log a one-time warning and return None for
    country. Caller still emits the row; the geocode pass can resolve
    location without a country bound.
    """
    cc_m = COUNTRY_RE.search(venue)
    cc2 = None
    if cc_m:
        raw = cc_m.group(1)
        cc2 = _ISO3_TO_ISO2.get(raw)
        if cc2 is None and raw not in _unmapped_seen:
            _unmapped_seen.add(raw)
            logger.warning(
                "Unmapped DUV country code %r — emitting row with empty country. "
                "Add to _ISO3_TO_ISO2 if it appears repeatedly.", raw,
            )
        venue = COUNTRY_RE.sub('', venue).strip().rstrip(',').strip()
    return venue, cc2


def fetch_page(year: int, page: int) -> str:
    params = {'year': year, 'dist': 'all', 'country': 'all', 'page': page}
    resp = requests.get(
        BASE,
        params=params,
        headers={'User-Agent': USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse(html_text: str) -> Iterable[dict]:
    for body in ROW_RE.findall(html_text):
        tds = TD_RE.findall(body)
        if len(tds) < 4:
            continue
        date_iso = _parse_date(_strip(tds[0]))
        if not date_iso:
            continue
        link_m = LINK_RE.search(tds[1])
        if not link_m:
            continue
        event_id, name = link_m.group(1), html.unescape(link_m.group(2)).strip()
        dist_raw = _strip(tds[2])
        dist_km = _parse_distance_km(dist_raw)
        if dist_km is None:
            continue
        venue, country = _split_venue(_strip(tds[3]))

        yield {
            'source': 'duv',
            'external_id': event_id,
            'name': name,
            'date': date_iso,
            'country': country or '',
            'region': '',
            'location': venue,
            'lat': '',
            'lon': '',
            'distance_km': dist_km,
            'elev_gain_m': '',
            'elev_loss_m': '',
            'surface': '',
            'race_type': _classify(dist_km),
            'itra_points': '',
            'url': f"https://statistik.d-u-v.org/eventdetail.php?event={event_id}",
            'description': '',
        }


def _total_pages(html_text: str) -> int:
    """Read 'X to Y of Z search results' and compute total pages.

    Falls back to 1 if the marker is absent (single-page result, or layout
    drift — caller will still emit whatever this page parsed).
    """
    m = TOTAL_RE.search(html_text)
    if not m:
        return 1
    total = int(m.group(3))
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def scrape_year(year: int) -> list[dict]:
    """Walk all calendar pages for ``year``. Page count is read off the
    first page's 'X to Y of Z' marker, so we don't rely on detecting an
    'is this the last page?' condition heuristically."""
    print(f"Fetching DUV {year} page 1…", file=sys.stderr)
    first = fetch_page(year, 1)
    pages = _total_pages(first)
    rows = list(parse(first))
    print(f"  {pages} page(s), {len(rows)} rows on page 1", file=sys.stderr)

    for page in range(2, pages + 1):
        time.sleep(PAGE_SLEEP_SEC)
        print(f"Fetching DUV {year} page {page}/{pages}…", file=sys.stderr)
        page_rows = list(parse(fetch_page(year, page)))
        if not page_rows:
            logger.warning("DUV page %d/%d returned 0 rows — stopping early", page, pages)
            break
        rows.extend(page_rows)
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    p = argparse.ArgumentParser()
    p.add_argument('--year', type=int, default=dt.date.today().year)
    p.add_argument('--out', type=Path, default=None)
    args = p.parse_args()

    out_path = args.out or BACKEND_ROOT / 'data' / f'duv_{args.year}.csv'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = scrape_year(args.year)
    if not rows:
        print("No rows scraped — DUV layout may have changed.", file=sys.stderr)
        return 1

    fieldnames = list(rows[0].keys())
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} races -> {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

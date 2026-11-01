"""Scrape the Sterrato Gang trail-running calendar into a CSV.

The site renders all race cards server-side as ``<div class="toy-card">``
elements with data attributes:

    data-nome   slugified race name
    data-prov   Italian province (display-cased)
    data-dist   distance in km (integer)
    data-disl   elevation gain D+ in metres (integer)

plus inner ``.tc-date``, ``.tc-title``, ``.tc-loc`` text. There is no per-race
URL, lat/lon, or external ID, so we synthesise an ``external_id`` from
``date + name-slug + province + distance`` (the distance disambiguates
multi-distance events held the same day in the same town).

Output CSV is the schema consumed by ``seed_races.py``: re-run scraper +
seeder safely; ``(source='sterratogang', external_id)`` upserts cleanly.

Usage:
    docker compose exec backend python scripts/scrape_sterratogang.py
    docker compose exec backend python scripts/seed_races.py data/sterratogang.csv
"""

from __future__ import annotations

import csv
import html
import re
import sys
from pathlib import Path
from typing import Iterable

import requests

URL = "https://www.sterratogang.it/calendario-gare-trailrunning/"
USER_AGENT = "Mozilla/5.0 (compatible; PaceMindBot/1.0; +https://pacemind.app)"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = BACKEND_ROOT / "data" / "sterratogang.csv"

CARD_OPEN_RE = re.compile(
    r'<div class="toy-card"\s+'
    r'data-nome="(?P<nome>[^"]*)"\s+'
    r'data-prov="(?P<prov>[^"]*)"\s+'
    r'data-dist="(?P<dist>[^"]*)"\s+'
    r'data-disl="(?P<disl>[^"]*)">',
)
DATE_RE = re.compile(r'<div class="tc-date">([^<]+)</div>')
TITLE_RE = re.compile(r'<div class="tc-title">([^<]+)</div>')
LOC_RE = re.compile(r'<div class="tc-loc">.*?<span>([^<]+)</span>', re.DOTALL)


def _slug(text: str) -> str:
    out, prev_dash = [], False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


def _parse_date(raw: str) -> str | None:
    """Site mixes 'DD/MM/YYYY' and 'D/M/YYYY' — normalise to 'YYYY-MM-DD'."""
    parts = raw.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _classify(distance_km: float) -> str:
    return "ultra" if distance_km >= 50 else "trail"


def parse(html_text: str) -> Iterable[dict]:
    seen_keys: set[str] = set()
    matches = list(CARD_OPEN_RE.finditer(html_text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html_text)
        body = html_text[start:end]
        date_m = DATE_RE.search(body)
        title_m = TITLE_RE.search(body)
        loc_m = LOC_RE.search(body)
        if not (date_m and title_m):
            continue

        date_iso = _parse_date(date_m.group(1))
        if not date_iso:
            continue

        try:
            dist_km = float(m.group("dist"))
        except ValueError:
            continue
        try:
            elev_m = float(m.group("disl"))
        except ValueError:
            elev_m = 0.0

        title = html.unescape(title_m.group(1)).strip()
        prov = html.unescape(m.group("prov")).strip()
        loc = html.unescape(loc_m.group(1)).strip().title() if loc_m else ""

        ext_id = f"{date_iso}-{_slug(title)}-{_slug(prov)}-{int(dist_km)}km"
        if ext_id in seen_keys:
            continue
        seen_keys.add(ext_id)

        location = ", ".join(p for p in (loc, prov) if p)

        yield {
            "source": "sterratogang",
            "external_id": ext_id,
            "name": title,
            "date": date_iso,
            "country": "IT",
            "region": "",
            "location": location,
            "lat": "",
            "lon": "",
            "distance_km": int(dist_km),
            "elev_gain_m": int(elev_m) if elev_m else "",
            "elev_loss_m": "",
            "surface": "trail",
            "race_type": _classify(dist_km),
            "itra_points": "",
            "url": URL,
            "description": "",
        }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {URL}", file=sys.stderr)
    resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    rows = list(parse(resp.text))
    if not rows:
        print("No race cards parsed — site layout may have changed.", file=sys.stderr)
        return 1

    fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} races -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

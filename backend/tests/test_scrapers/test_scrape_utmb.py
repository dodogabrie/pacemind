"""Smoke tests for the UTMB World Series scraper.

The scraper has two phases (index → per-tenant detail). These tests stub
out the network with the saved fixtures and verify:
  - the index parser picks the events list out of __NEXT_DATA__
  - the detail parser pulls real distance/elev from listOfRaces
  - the band fallback fires when the tenant fetch returns nothing
  - human-formatted dates ("17th July 2026") parse correctly
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import scripts.scrape_utmb as utmb

FIXTURES = Path(__file__).parent / 'fixtures'


def _next_data(path: Path) -> dict:
    html = path.read_text()
    blob = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    ).group(1)
    return json.loads(blob)


@pytest.fixture()
def index_events() -> list[dict]:
    data = _next_data(FIXTURES / 'utmb_index.html')
    slices = data['props']['pageProps']['slices']
    for sl in slices:
        events = sl.get('data', {}).get('events')
        if events:
            return events
    raise AssertionError("fixture has no events")


@pytest.fixture()
def tenant_races() -> list[dict]:
    data = _next_data(FIXTURES / 'utmb_tenant.html')
    for sl in data['props']['pageProps']['slices']:
        if sl.get('type') == 'listOfRaces':
            return sl['data']['races']
    raise AssertionError("fixture has no listOfRaces slice")


def test_index_fixture_has_two_events(index_events):
    assert len(index_events) == 2
    assert {e['tenant'] for e in index_events} == {'mrww', 'utmb'}


def test_human_date_parser():
    assert utmb._parse_human_date("17th July 2026", "2026-01-01") == "2026-07-17"
    assert utmb._parse_human_date("1st May 2026", "2026-01-01") == "2026-05-01"
    assert utmb._parse_human_date("3rd Sep 2026", "2026-01-01") == "2026-09-03"
    # Garbage falls back to the event start date.
    assert utmb._parse_human_date("???", "2026-08-25") == "2026-08-25"


def test_row_from_detail_uses_real_distance(index_events, tenant_races):
    event = next(e for e in index_events if e['tenant'] == 'mrww')
    rows = [utmb._row_from_detail(event, r) for r in tenant_races]
    rows = [r for r in rows if r is not None]
    assert len(rows) == 2

    mrt = next(r for r in rows if r['external_id'] == 'mrww-MRT')
    assert mrt['distance_km'] == 82.0  # real distance, not the band's 100
    assert mrt['elev_gain_m'] == 6300.0
    # The ws100KM band is normalised onto the canonical taxonomy using the
    # *real* 82 km, not the band's nominal 100. Storing the raw band here used
    # to leak `races.type.ws100KM` into the UI and score as an unknown category.
    assert mrt['race_type'] == 'ultra'
    assert mrt['country'] == 'IT'
    assert mrt['lat'] == pytest.approx(45.7768)
    assert mrt['date'] == '2026-07-17'

    wt = next(r for r in rows if r['external_id'] == 'mrww-WT')
    assert wt['distance_km'] == 48.0
    assert wt['elev_gain_m'] == 3200.0


def test_band_fallback_when_detail_empty(index_events, monkeypatch):
    """When fetch_tenant_races returns [] (offline tenant), expand() must
    fall back to band-derived rows so the event isn't dropped."""
    monkeypatch.setattr(utmb, 'fetch_tenant_races', lambda _url: [])
    monkeypatch.setattr(utmb.time, 'sleep', lambda _s: None)

    rows = list(utmb.expand(index_events, fetch_detail=True))
    # 2 events × 4+3 raceCategories = 7 fallback rows
    assert len(rows) == 7
    # All rows have nominal band km, not real distances.
    mrww_100m = next(r for r in rows if r['external_id'] == 'mrww-2026-07-17-ws100M')
    assert mrww_100m['distance_km'] == 161.0  # nominal
    # external_id keeps the raw band (it is an identity — rewriting it would
    # duplicate rows on upsert), but race_type is canonical.
    assert mrww_100m['race_type'] == 'ultra'


def test_expand_prefers_detail_over_fallback(index_events, tenant_races, monkeypatch):
    """When detail succeeds for one tenant and fails for the other, the
    successful tenant uses real distances; the other falls back."""
    def fake_fetch(url):
        return tenant_races if 'mrww' in url else []
    monkeypatch.setattr(utmb, 'fetch_tenant_races', fake_fetch)
    monkeypatch.setattr(utmb.time, 'sleep', lambda _s: None)

    rows = list(utmb.expand(index_events, fetch_detail=True))
    by_ext = {r['external_id']: r for r in rows}

    # mrww uses detail rows (slug-based ext_id, real distances)
    assert 'mrww-MRT' in by_ext
    assert by_ext['mrww-MRT']['distance_km'] == 82.0
    # utmb falls back (band-based ext_id, nominal distances)
    assert any(k.startswith('utmb-2026-08-25-ws') for k in by_ext)


def test_no_detail_mode_emits_band_rows_only(index_events):
    rows = list(utmb.expand(index_events, fetch_detail=False))
    assert len(rows) == 7  # 4 + 3 categories
    assert all(r['external_id'].count('-') >= 4 for r in rows)  # tenant-YYYY-MM-DD-band

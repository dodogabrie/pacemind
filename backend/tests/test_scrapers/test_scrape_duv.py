"""Smoke tests for the DUV calendar scraper.

These pin the parser to a small, hand-curated HTML fixture. If DUV ever
changes their table markup, these tests fail fast — that's the contract.
The fixture covers: km event, mi event, time-only event (must be filtered),
stage-race notation, and an unknown country code (must warn but still emit).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import scripts.scrape_duv as duv

FIXTURE = Path(__file__).parent / 'fixtures' / 'duv_calendar_page.html'


@pytest.fixture()
def fixture_html() -> str:
    return FIXTURE.read_text()


def test_total_pages_from_marker(fixture_html):
    # 4275 / 1000 → 5 pages
    assert duv._total_pages(fixture_html) == 5


def test_total_pages_no_marker_returns_one():
    assert duv._total_pages("<html>no marker here</html>") == 1


def test_parse_filters_time_only_events(fixture_html):
    rows = list(duv.parse(fixture_html))
    # 5 source rows, '24h' is dropped → 4 emitted.
    assert len(rows) == 4
    assert all(r['external_id'] != '12347' for r in rows), "24h event should be filtered"


def test_parse_extracts_core_fields(fixture_html):
    rows = {r['external_id']: r for r in duv.parse(fixture_html)}

    swiss = rows['12345']
    assert swiss['name'] == 'Sample Trail 50'
    assert swiss['date'] == '2026-05-15'
    assert swiss['distance_km'] == 50.0
    assert swiss['country'] == 'CH'  # SUI → CH
    assert swiss['location'] == 'Bern, BE'
    assert swiss['race_type'] == 'ultra'

    us_mi = rows['12346']
    assert us_mi['country'] == 'US'
    assert us_mi['distance_km'] == round(100 * 1.609344, 1)  # 160.9
    assert us_mi['race_type'] == 'ultra'

    stage = rows['12348']
    assert stage['distance_km'] == 230.0  # leading km of "230km/6stages"
    assert stage['country'] == 'MA'  # MAR → MA


def test_unknown_country_logs_warning_and_emits_row(fixture_html, caplog):
    duv._unmapped_seen.clear()
    with caplog.at_level(logging.WARNING, logger=duv.__name__):
        rows = list(duv.parse(fixture_html))
    by_id = {r['external_id']: r for r in rows}
    assert '12349' in by_id, "unknown-country row must still be emitted"
    assert by_id['12349']['country'] == ''
    assert any('XYZ' in rec.message for rec in caplog.records), \
        "expected a warning naming the unmapped code"


def test_warning_only_fires_once_per_unknown_code(caplog):
    duv._unmapped_seen.clear()
    html = "Unknown City (ZZZ)\nUnknown Town (ZZZ)"
    with caplog.at_level(logging.WARNING, logger=duv.__name__):
        for _ in range(3):
            duv._split_venue("Unknown City (ZZZ)")
    zzz_warns = [r for r in caplog.records if 'ZZZ' in r.message]
    assert len(zzz_warns) == 1, "warning must dedupe across calls"

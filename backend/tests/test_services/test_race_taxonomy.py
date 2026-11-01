"""Race-type normalisation (GH #78).

``races.race_type`` is documented as ``road|trail|ultra|vertical``, but the UTMB
scraper wrote World Series distance bands (``ws50KM``, ``ws100M``, ...) into it.
These tests pin the mapping and, just as importantly, pin what must *not* be
rewritten.
"""

import pytest

from services.race_taxonomy import (
    CANONICAL_RACE_TYPES,
    ULTRA_THRESHOLD_KM,
    is_distance_band,
    normalise_race_type,
)


@pytest.mark.parametrize('band', ['ws20KM', 'ws50KM', 'ws100KM', 'ws50M', 'ws100M'])
def test_every_known_band_maps_into_the_canonical_taxonomy(band):
    result = normalise_race_type(band, None, 'trail')
    assert result in CANONICAL_RACE_TYPES
    assert not is_distance_band(result)


@pytest.mark.parametrize('band,distance_km,expected', [
    ('ws20KM', 20.0, 'trail'),
    ('ws50KM', 50.0, 'ultra'),
    ('ws100KM', 100.0, 'ultra'),
    ('ws50M', 80.0, 'ultra'),
    ('ws100M', 161.0, 'ultra'),
])
def test_band_maps_by_distance(band, distance_km, expected):
    assert normalise_race_type(band, distance_km, 'trail') == expected


def test_real_distance_wins_over_the_band_nominal():
    """The band is a bracket, not a measurement: a 'ws100KM' race that is
    actually 82 km (UTMB's MRT) must be typed from the 82, and a 'ws50KM' that
    is really 38 km is a plain trail race, not an ultra."""
    assert normalise_race_type('ws100KM', 82.0, 'trail') == 'ultra'
    assert normalise_race_type('ws50KM', 38.0, 'trail') == 'trail'


def test_marathon_distance_is_the_ultra_boundary():
    assert normalise_race_type('ws50KM', ULTRA_THRESHOLD_KM, 'trail') == 'ultra'
    assert normalise_race_type('ws50KM', ULTRA_THRESHOLD_KM - 0.001, 'trail') == 'trail'


def test_road_surface_bands_do_not_become_trail():
    assert normalise_race_type('ws20KM', 20.0, 'asphalt') == 'road'
    assert normalise_race_type('ws100KM', 100.0, 'road') == 'ultra'


@pytest.mark.parametrize('value', ['road', 'trail', 'ultra', 'vertical'])
def test_canonical_values_pass_through(value):
    assert normalise_race_type(value, 42.0, 'trail') == value


def test_canonical_values_are_case_normalised():
    assert normalise_race_type('Trail', 20.0, 'trail') == 'trail'
    assert normalise_race_type('ULTRA', 90.0, 'trail') == 'ultra'


def test_unknown_vocabulary_is_left_alone_not_discarded():
    """This normalises one known-bad vocabulary; it is not a whitelist.
    Silently dropping unrecognised types would lose data."""
    assert normalise_race_type('marathon', 42.2, 'road') == 'marathon'
    assert normalise_race_type('skyrace', 30.0, 'trail') == 'skyrace'


@pytest.mark.parametrize('value', [None, '', '   '])
def test_empty_input_normalises_to_none(value):
    assert normalise_race_type(value, 42.0, 'trail') is None


def test_normalisation_is_idempotent():
    once = normalise_race_type('ws100KM', 82.0, 'trail')
    assert normalise_race_type(once, 82.0, 'trail') == once


def test_is_distance_band_identifies_only_bands():
    assert is_distance_band('ws50KM')
    assert is_distance_band('ws50km')  # case-insensitive
    assert not is_distance_band('ultra')
    assert not is_distance_band(None)
    assert not is_distance_band('')

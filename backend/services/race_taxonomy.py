"""Canonical race-type taxonomy.

``Race.race_type`` is documented as ``road|trail|ultra|vertical``, but the UTMB
World Series feed exposes a *distance band* (``categoryWorldSeries``) using its
own vocabulary — ``ws20KM``, ``ws50KM``, ``ws100KM``, ``ws50M``, ``ws100M``.
Those bands were being written straight into ``race_type``, which mixed two
vocabularies in one column and had three visible consequences:

* the UI rendered the raw i18n key (``races.type.ws50KM``) as the race's badge;
* the race-type filter, which offers only the canonical values, could never
  select those races;
* ``_score_race`` treated the band as an unknown category and fell back to the
  neutral 0.5, mis-ranking them against correctly-typed races.

Normalising happens at ingestion (see ``scripts/scrape_utmb.py`` and
``scripts/seed_races.py``); migration ``n1a2b3c4d5f3`` backfills existing rows.

A band carries no information that ``distance_km`` doesn't already hold, so it
is mapped rather than preserved. The band still appears in ``external_id`` for
band-fallback rows — that is an identity, not a category, and must not change.
"""

from typing import Optional

#: Values ``Race.race_type`` is allowed to hold.
CANONICAL_RACE_TYPES = frozenset({'road', 'trail', 'ultra', 'vertical'})

#: UTMB World Series distance bands → nominal km, used only when a race has no
#: measured distance of its own.
_BAND_NOMINAL_KM = {
    'ws20km': 20.0,
    'ws50km': 50.0,
    'ws100km': 100.0,
    'ws50m': 80.0,
    'ws100m': 161.0,
}

#: Classic ultra threshold: anything beyond the marathon distance.
ULTRA_THRESHOLD_KM = 42.195


def is_distance_band(raw: Optional[str]) -> bool:
    """True if ``raw`` is a UTMB World Series band rather than a race type."""
    return bool(raw) and raw.strip().lower() in _BAND_NOMINAL_KM


def normalise_race_type(
    raw: Optional[str],
    distance_km: Optional[float] = None,
    surface: Optional[str] = None,
) -> Optional[str]:
    """Map ``raw`` onto the canonical taxonomy.

    Already-canonical values pass through (lowercased). Unrecognised values are
    returned untouched rather than discarded — this normalises a known-bad
    vocabulary, it is not a whitelist.

    A distance band resolves via the race's measured ``distance_km`` when there
    is one, falling back to the band's nominal distance. UTMB World Series is a
    trail series, so a sub-marathon band is ``trail`` and anything longer is
    ``ultra``.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in CANONICAL_RACE_TYPES:
        return lowered
    if lowered not in _BAND_NOMINAL_KM:
        return value

    km = distance_km if distance_km else _BAND_NOMINAL_KM[lowered]
    if (surface or 'trail').strip().lower() in ('asphalt', 'road', 'track'):
        return 'road' if km < ULTRA_THRESHOLD_KM else 'ultra'
    return 'ultra' if km >= ULTRA_THRESHOLD_KM else 'trail'

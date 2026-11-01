"""UTC coercion for datetimes that round-trip through naive DB columns.

Regression cover for the Strava activity-list cache returning 500: `fetched_at`
is a naive `db.DateTime`, so comparing it against `datetime.now(timezone.utc)`
raised "can't subtract offset-naive and offset-aware datetimes" on every
cached read.
"""

from datetime import datetime, timedelta, timezone

from models.strava_activity_cache import StravaActivityCache
from utils.datetime_utils import as_utc, utc_now


def test_naive_value_is_interpreted_as_utc():
    naive = datetime(2026, 8, 21, 12, 0, 0)
    result = as_utc(naive)
    assert result.tzinfo is timezone.utc
    assert result.replace(tzinfo=None) == naive  # no wall-clock shift


def test_aware_value_is_converted_not_reinterpreted():
    aware = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    result = as_utc(aware)
    assert result.tzinfo is timezone.utc
    assert result.hour == 10


def test_none_passes_through():
    assert as_utc(None) is None


def test_is_idempotent():
    once = as_utc(datetime(2026, 8, 21, 12, 0, 0))
    assert as_utc(once) == once


def test_naive_and_aware_become_comparable():
    """The actual failure: this subtraction used to raise TypeError."""
    # What Postgres hands back for a `db.DateTime` column: no tzinfo.
    naive_from_db = utc_now().replace(tzinfo=None)
    assert (utc_now() - as_utc(naive_from_db)).total_seconds() >= 0


def test_is_stale_survives_a_naive_fetched_at():
    """Postgres hands `fetched_at` back naive, which used to 500 the endpoint."""
    cache = StravaActivityCache()
    cache.fetched_at = (utc_now() - timedelta(hours=1)).replace(tzinfo=None)
    assert cache.is_stale(max_age_hours=24) is False
    assert cache.is_stale(max_age_hours=0.5) is True


def test_is_stale_still_works_with_an_aware_fetched_at():
    cache = StravaActivityCache()
    cache.fetched_at = utc_now() - timedelta(hours=1)
    assert cache.is_stale(max_age_hours=24) is False
    assert cache.is_stale(max_age_hours=0.5) is True

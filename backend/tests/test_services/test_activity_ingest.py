"""ActivityIngestService — dedup, source precedence, and the upsert.

The acceptance criterion this file locks in: the same session arriving from
two different sources yields ONE row, with the higher-precedence source's
streams winning.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from database import db
from models import Activity, User
from services.activity_ingest import ActivityIngestService, NormalizedActivity
from services.activity_ingest.normalizers.strava import normalize_strava

START = datetime(2026, 3, 14, 6, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def user_id(app):
    u = User(strava_user_id=1234, strava_username='ingest')
    db.session.add(u)
    db.session.commit()
    return u.id


@pytest.fixture
def svc(tmp_path):
    """No residual collection: this suite is about the row, not the ML."""
    from services.cache_service import CacheService
    return ActivityIngestService(cache_service=CacheService(cache_dir=str(tmp_path)))


def _streams(marker):
    return {'time': [0, 1, 2], 'distance': [0.0, 3.0, 6.0],
            'velocity_smooth': [marker, marker, marker],
            'grade_smooth': [0.0, 0.0, 0.0]}


def _norm(source, external_id, marker, start=START, distance=21097.0):
    return NormalizedActivity(
        source=source, external_id=external_id, name='Sunday long run',
        start_date=start, distance_m=distance, streams=_streams(marker),
        sport_type='trail_run')


def test_same_session_from_two_sources_is_one_row(app, user_id, svc):
    svc.ingest(user_id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    db.session.commit()

    # Same run as the device recorded it: 20 s later start, 13 m longer.
    # Both land in the same minute / 50 m dedup buckets.
    svc.ingest(user_id, _norm('garmin', 'g-abc', marker=3.5,
                              start=START + timedelta(seconds=20),
                              distance=21110.0), collect_residuals=False)
    db.session.commit()

    rows = Activity.query.filter_by(user_id=user_id).all()
    assert len(rows) == 1
    row = rows[0]
    # Garmin outranks Strava: its streams replace, and the id is recorded.
    assert row.source == 'garmin'
    assert row.external_id == 'g-abc'
    assert row.streams['velocity_smooth'][0] == 3.5
    # The Strava id is not thrown away.
    assert row.strava_id == 555


def test_lower_precedence_arrival_keeps_existing_streams(app, user_id, svc):
    svc.ingest(user_id, _norm('garmin', 'g-abc', marker=3.5), collect_residuals=False)
    db.session.commit()

    svc.ingest(user_id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    db.session.commit()

    rows = Activity.query.filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].source == 'garmin'
    assert rows[0].streams['velocity_smooth'][0] == 3.5
    assert rows[0].strava_id == 555  # id linked, streams untouched


def test_same_source_reingest_refreshes_not_duplicates(app, user_id, svc):
    svc.ingest(user_id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    db.session.commit()
    svc.ingest(user_id, _norm('strava', '555', marker=9.9), collect_residuals=False)
    db.session.commit()

    rows = Activity.query.filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].streams['velocity_smooth'][0] == 9.9


def test_distinct_sessions_are_not_collapsed(app, user_id, svc):
    svc.ingest(user_id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    svc.ingest(user_id, _norm('strava', '556', marker=2.5,
                              start=START + timedelta(hours=3)),
               collect_residuals=False)
    # Same start, very different distance — a different session.
    svc.ingest(user_id, _norm('strava', '557', marker=2.5, distance=5000.0),
               collect_residuals=False)
    db.session.commit()

    assert Activity.query.filter_by(user_id=user_id).count() == 3


def test_dedup_is_scoped_to_the_user(app, user_id, svc):
    other = User(strava_user_id=999, strava_username='other')
    db.session.add(other)
    db.session.commit()

    svc.ingest(user_id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    svc.ingest(other.id, _norm('strava', '555', marker=2.5), collect_residuals=False)
    db.session.commit()

    assert Activity.query.count() == 2


def test_unknown_source_is_refused(app):
    with pytest.raises(ValueError, match='unknown activity source'):
        NormalizedActivity(source='fitbit', external_id='1', name='x',
                           start_date=START, distance_m=1000.0)


def test_strava_normalizer_maps_the_payload(app):
    n = normalize_strava({
        'id': 12345,
        'name': 'Trail loop',
        'distance': 15000.0,
        'start_date': '2026-03-14T06:30:00Z',
        'moving_time': 5400,
        'elapsed_time': 5700,
        'total_elevation_gain': 620.0,
        'sport_type': 'TrailRun',
    }, _streams(2.0))

    assert (n.source, n.external_id, n.sport_type) == ('strava', '12345', 'trail_run')
    assert n.start_date == START
    assert (n.moving_time_s, n.elapsed_time_s, n.elevation_gain_m) == (5400, 5700, 620.0)


def test_cache_streams_routes_through_ingest(app, user_id, tmp_path):
    """CacheService is a caller of the single write path, not a second one."""
    from services.cache_service import CacheService

    cache = CacheService(cache_dir=str(tmp_path))
    cache.cache_streams(user_id, 777, 'Cached run', 8000.0, START, _streams(2.0))
    cache.cache_streams(user_id, 777, 'Cached run', 8000.0, START, _streams(4.0))

    rows = Activity.query.filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].source == 'strava'
    assert rows[0].strava_id == 777
    assert rows[0].dedup_key is not None
    assert rows[0].streams['velocity_smooth'][0] == 4.0


def test_same_session_across_a_bucket_boundary_is_one_row(app, user_id, svc):
    """multi-source #83: `round()` is a bucket, not a tolerance.

    21097 m and 21127 m are 30 m apart but land in distance buckets 422 and
    423, and :29.6 vs :30.4 straddles the minute bucket. Both are well inside
    the disagreement a watch and a provider's re-processing produce, so both
    must resolve to the same row via the neighbour-bucket probe.
    """
    edge = START.replace(second=29, microsecond=600000)
    svc.ingest(user_id, _norm('strava', '555', marker=2.5, start=edge,
                              distance=21097.0), collect_residuals=False)
    db.session.commit()

    svc.ingest(user_id, _norm('garmin', 'g-abc', marker=3.5,
                              start=START.replace(second=30, microsecond=400000),
                              distance=21127.0), collect_residuals=False)
    db.session.commit()

    rows = Activity.query.filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].source == 'garmin'
    assert rows[0].streams['velocity_smooth'][0] == 3.5


def test_the_distance_tolerance_is_relative_to_the_distance(app, user_id, svc):
    """A 100 m disagreement is nothing over a 170 km ultra, everything over 5 km."""
    ultra = 170_000.0
    svc.ingest(user_id, _norm('strava', '900', marker=2.5, distance=ultra),
               collect_residuals=False)
    db.session.commit()
    svc.ingest(user_id, _norm('garmin', 'g-900', marker=3.5, distance=ultra + 300),
               collect_residuals=False)
    db.session.commit()
    assert Activity.query.filter_by(user_id=user_id).count() == 1

    # Same absolute delta on a short run is a different session.
    short_start = START + timedelta(days=5)
    svc.ingest(user_id, _norm('strava', '901', marker=2.5, start=short_start,
                              distance=5000.0), collect_residuals=False)
    svc.ingest(user_id, _norm('garmin', 'g-901', marker=3.5, start=short_start,
                              distance=5300.0), collect_residuals=False)
    db.session.commit()
    assert Activity.query.filter_by(user_id=user_id).count() == 3


def test_local_date_falls_back_to_utc_when_unknown(app, user_id, svc):
    """No coordinates, no Strava wall clock: the UTC date is what we have."""
    activity = svc.ingest(user_id, _norm('strava', '777', marker=2.5),
                          collect_residuals=False)
    db.session.commit()
    assert activity.local_date == START.date()

"""Race flag: detector scoring, Strava flag ingest (user wins), API, migration."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

from api.auth import generate_jwt
from app import create_app
from database import db
from models import Activity, Race, User
from services import race_detection_service as rds
from services.activity_ingest import ActivityIngestService
from services.activity_ingest.normalizers.strava import normalize_strava

SUNDAY = datetime(2026, 5, 10, 8, 0)  # a Sunday


def _act(name='Morning Trail Run', day=SUNDAY, km=20.0, dplus=800, moving=9000, lat=None, lng=None, id=1):
    return SimpleNamespace(id=id, name=name, distance=km * 1000, elevation_gain_m=dplus, moving_time_s=moving,
                           start_date=day, start_date_local=day, local_date=day.date(),
                           start_lat=lat, start_lng=lng)


def _history(n=10, moving=9000):
    return [_act(day=SUNDAY - timedelta(days=7 * (i + 1)), moving=moving, id=100 + i) for i in range(n)]


def _race(name='Trail del Montanaro', km=42.0, lat=45.0, lon=7.8, day=SUNDAY.date()):
    return SimpleNamespace(id=9, name=name, distance_km=km, lat=lat, lon=lon, date=day)


def codes(s):
    return {r['code'] for r in s['reasons']}


def test_default_watch_names_are_not_a_signal_but_race_words_are():
    tue = datetime(2026, 5, 12, 18, 0)
    for n in ('Morning Trail Run', 'Sessione di trail running mattutina', 'Evening Run'):
        assert rds.score_activity(_act(n, day=tue), [], [], [])['score'] == 0
    s = rds.score_activity(_act('Gara Trail del Montanaro', day=tue), [], [], [])
    assert s['score'] >= rds.CANDIDATE_MIN_SCORE and codes(s) == {'name'}
    assert rds.score_activity(_act('Maratonina di Prato', day=tue), [], [], [])['score'] >= 0.4
    assert rds.score_activity(_act('Montanaro trail 2026', day=tue), [], [], [])['score'] == pytest.approx(0.3)


def test_calendar_match_needs_same_day_distance_and_place():
    a = _act(km=42.5, lat=45.01, lng=7.81)
    assert 'calendar' in codes(rds.score_activity(a, [], [_race()], []))
    far = _act(km=42.5, lat=38.0, lng=-9.0)                      # another country
    assert 'calendar' not in codes(rds.score_activity(far, [], [_race()], []))
    no_coords = _act(km=42.5)                                    # summary row before resync
    assert 'calendar' not in codes(rds.score_activity(no_coords, [], [_race()], []))
    short = _act(km=21, lat=45.01, lng=7.81)
    assert 'calendar' not in codes(rds.score_activity(short, [], [_race()], []))


def test_planned_race_is_the_post_race_question():
    planned = [{'date': SUNDAY.date() + timedelta(days=1), 'name': 'Lavaredo 50K', 'km': 50.0, 'race_id': 3}]
    s = rds.score_activity(_act(km=49, day=SUNDAY + timedelta(hours=16)), [], [], planned)
    assert 'planned' in codes(s) and s['score'] >= rds.CANDIDATE_MIN_SCORE


def test_effort_and_weekend_morning():
    fast = _act(moving=7600, day=datetime(2026, 5, 12, 18, 0))   # ~16 % faster, Tuesday evening
    s = rds.score_activity(fast, _history(), [], [])
    assert codes(s) == {'effort'} and s['reasons'][0]['detail'] >= 10
    same = rds.score_activity(_act(), _history(), [], [])
    assert codes(same) == {'weekend_morning'} and same['score'] < rds.CANDIDATE_MIN_SCORE
    assert 'effort' not in codes(rds.score_activity(fast, _history(3), [], []))  # too little history


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
def user(app):
    u = User(email='r@runner.io', auth_provider='email')
    db.session.add(u)
    db.session.commit()
    return u


def _row(user, name, day, km=20.0, **kw):
    a = Activity(user_id=user.id, source='strava', external_id=name + str(day), name=name, distance=km * 1000,
                 start_date=day, start_date_local=day, sport_type='trail_run', moving_time_s=9000,
                 elevation_gain_m=800, **kw)
    db.session.add(a)
    return a


def test_race_overview_candidates_marked_and_prompt(user):
    now = datetime(2026, 9, 1)
    _row(user, 'Gara del Mugello', datetime(2026, 6, 7, 8))              # candidate (name)
    _row(user, 'Skyrace rejected', datetime(2026, 6, 14, 8), race_source='user')   # user said no
    _row(user, 'Old race', datetime(2025, 6, 1, 8), is_race=True, race_source='strava_flag')
    _row(user, 'Lavaredo 50K', datetime(2026, 6, 26, 8), km=50, start_lat=46.54, start_lng=12.13)
    db.session.add(Race(name='Lavaredo Ultra Trail 50K', slug='lut50', date=date(2026, 6, 26),
                        distance_km=50, lat=46.54, lon=12.13))
    db.session.commit()

    out = rds.race_overview(user.id, now=now)
    names = [c['name'] for c in out['candidates']]
    assert names == ['Gara del Mugello', 'Lavaredo 50K']                  # by score: name+weekend, calendar
    assert 'Skyrace rejected' not in names
    assert [m['name'] for m in out['marked']] == ['Old race']
    assert out['has_recent_race'] is False                               # marked one is > 12 months old


def test_strava_flag_ingest_backfill_and_user_wins(user, tmp_path):
    from services.cache_service import CacheService
    svc = ActivityIngestService(cache_service=CacheService(cache_dir=str(tmp_path)))
    payload = {'id': 77, 'name': 'Trail race', 'start_date': '2026-05-10T06:00:00Z', 'distance': 21000,
               'moving_time': 8000, 'elapsed_time': 8200, 'sport_type': 'TrailRun', 'workout_type': 1,
               'start_latlng': [45.0, 7.8]}
    a = svc.ingest(user.id, normalize_strava(payload), collect_residuals=False)
    assert (a.is_race, a.race_source, a.start_lat) == (True, 'strava_flag', 45.0)

    # Un-flagged on Strava -> cleared; a summary without workout_type leaves it alone.
    a = svc.ingest(user.id, normalize_strava({**payload, 'workout_type': 0}), collect_residuals=False)
    assert (a.is_race, a.race_source) == (False, None)
    a = svc.ingest(user.id, normalize_strava({**payload, 'workout_type': 1}), collect_residuals=False)
    no_key = {k: v for k, v in payload.items() if k != 'workout_type'}
    assert svc.ingest(user.id, normalize_strava(no_key), collect_residuals=False).is_race is True

    # The user's call survives the next sync.
    a.is_race, a.race_source = False, 'user'
    a = svc.ingest(user.id, normalize_strava(payload), collect_residuals=False)
    assert (a.is_race, a.race_source) == (False, 'user')


def test_mark_race_endpoint(app, user, monkeypatch):
    import services.parameter_learning_service as pls
    calls = []
    monkeypatch.setattr(pls, 'train_async', calls.append)
    with_streams = _row(user, 'Race A', datetime(2026, 6, 7, 8))
    with_streams.streams = {'distance': [0, 10]}
    summary = _row(user, 'Race B', datetime(2026, 6, 8, 8))
    other = User(email='o@runner.io', auth_provider='email')
    db.session.add(other)
    db.session.commit()
    client = app.test_client()
    client.set_cookie(key='jwt_token', value=generate_jwt(user.id), domain='localhost')

    r = client.post(f'/api/activities/{with_streams.id}/race', json={'is_race': True})
    assert r.status_code == 200 and r.get_json()['race_source'] == 'user'
    assert db.session.get(Activity, with_streams.id).is_race is True
    assert calls == [user.id]                                           # retrain in background
    assert client.post(f'/api/activities/{summary.id}/race', json={'is_race': False}).status_code == 200
    assert calls == [user.id]                                           # no streams: nothing to retrain
    assert client.post(f'/api/activities/{summary.id}/race', json={'is_race': 'yes'}).status_code == 400

    client.set_cookie(key='jwt_token', value=generate_jwt(other.id), domain='localhost')
    assert client.post(f'/api/activities/{with_streams.id}/race', json={'is_race': False}).status_code == 404
    assert client.get('/api/activities/races').get_json()['candidates'] == []


def test_migration_adds_race_columns_idempotently(tmp_path):
    from flask_migrate import downgrade as alembic_downgrade, upgrade as alembic_upgrade
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{tmp_path / 'm.db'}"
    with app.app_context():
        alembic_upgrade(revision='q1a2b3c4d5f6')
        db.session.execute(text("INSERT INTO users (email, auth_provider) VALUES ('m@x.io', 'email')"))
        db.session.execute(text("INSERT INTO activities (user_id, source, name, distance, start_date) "
                                "VALUES (1, 'strava', 'r', 10000, '2026-01-01 08:00:00')"))
        db.session.commit()

        alembic_upgrade(revision='r1a2b3c4d5f7')
        alembic_upgrade(revision='r1a2b3c4d5f7')  # re-run: no-op
        cols = {c['name'] for c in inspect(db.engine).get_columns('activities')}
        assert {'is_race', 'race_source', 'start_lat', 'start_lng'} <= cols
        row = db.session.execute(text('SELECT is_race, race_source FROM activities')).one()
        assert (bool(row.is_race), row.race_source) == (False, None)

        alembic_downgrade(revision='q1a2b3c4d5f6')
        cols = {c['name'] for c in inspect(db.engine).get_columns('activities')}
        assert 'is_race' not in cols and 'race_source' not in cols
        db.session.remove()

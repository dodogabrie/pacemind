"""Tests for the race calendar API and repository."""

from datetime import date, datetime, timedelta

import pytest

from app import create_app
from database import db
from models import Race, TrainingPlan, User
from repositories.race_repository import RaceRepository


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
def client(app):
    return app.test_client()


# Race dates are anchored to "today" rather than hardcoded: the races API
# filters out past events (RaceRepository.search -> Race.date >= start_date),
# so fixed calendar dates silently turn every list assertion into 0 rows once
# they fall into the past. Keep the relative offsets, not the absolute dates.
TODAY = date.today()
RACE_NEAR = TODAY + timedelta(days=60)    # Turin Marathon (default)
RACE_MID = TODAY + timedelta(days=90)     # Susa Trail
RACE_FAR = TODAY + timedelta(days=180)    # Berlin Marathon


def _make_race(**overrides):
    defaults = dict(
        source='seed',
        external_id=overrides.get('external_id', 'race-x'),
        name='Race X',
        slug=overrides.get('slug', 'race-x'),
        date=RACE_NEAR,
        country='IT',
        location='Turin',
        lat=45.07,
        lon=7.69,
        distance_km=42.0,
        elev_gain_m=400.0,
        surface='asphalt',
        race_type='road',
    )
    defaults.update(overrides)
    return Race(**defaults)


@pytest.fixture
def seeded_races(app):
    """Three races: a Turin marathon, a near-Turin trail, a far Berlin marathon."""
    with app.app_context():
        races = [
            _make_race(external_id='r1', slug='r1', name='Turin Marathon'),
            _make_race(
                external_id='r2', slug='r2', name='Susa Trail',
                date=RACE_MID, distance_km=60.0, elev_gain_m=2800.0,
                lat=45.13, lon=7.05, surface='trail', race_type='ultra',
                location='Susa',
            ),
            _make_race(
                external_id='r3', slug='r3', name='Berlin Marathon',
                date=RACE_FAR, country='DE',
                lat=52.52, lon=13.40, location='Berlin',
            ),
        ]
        db.session.add_all(races)
        db.session.commit()
        yield [r.id for r in races]


def _login(client, app, user_id):
    from api.auth import generate_jwt
    with app.app_context():
        token = generate_jwt(user_id)
    client.set_cookie(key='jwt_token', value=token, domain='localhost')


def _make_user(app, **overrides):
    with app.app_context():
        u = User(
            strava_user_id=overrides.pop('strava_user_id', 7),
            strava_username='runner',
            training_base_lat=45.07,
            training_base_lon=7.69,
            training_base_name='Turin',
            training_travel_radius_km=120,
            **overrides,
        )
        db.session.add(u)
        db.session.commit()
        return u.id


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class TestRaceRepository:
    def test_search_filters_by_country(self, app, seeded_races):
        with app.app_context():
            rows = RaceRepository().search(country='IT')
            names = sorted(r.name for r in rows)
            assert names == ['Susa Trail', 'Turin Marathon']

    def test_search_filters_by_distance_band(self, app, seeded_races):
        with app.app_context():
            rows = RaceRepository().search(min_distance_km=50)
            assert {r.name for r in rows} == {'Susa Trail'}

    def test_search_near_me_excludes_far_races(self, app, seeded_races):
        with app.app_context():
            rows = RaceRepository().search(
                near_lat=45.07, near_lon=7.69, max_travel_km=200,
            )
            assert {r.name for r in rows} == {'Turin Marathon', 'Susa Trail'}

    def test_search_full_text_q(self, app, seeded_races):
        with app.app_context():
            rows = RaceRepository().search(q='berlin')
            assert {r.name for r in rows} == {'Berlin Marathon'}


# ---------------------------------------------------------------------------
# GET /api/races
# ---------------------------------------------------------------------------

class TestRacesList:
    def test_returns_all_by_default(self, client, seeded_races):
        resp = client.get('/api/races')
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body['races']) == 3

    def test_filters_by_country(self, client, seeded_races):
        resp = client.get('/api/races?country=IT')
        assert resp.status_code == 200
        names = {r['name'] for r in resp.get_json()['races']}
        assert names == {'Turin Marathon', 'Susa Trail'}

    def test_near_me_decorates_distance_and_fit(self, client, seeded_races):
        resp = client.get(
            '/api/races'
            '?near_lat=45.07&near_lon=7.69&max_travel_km=300'
            '&target_distance_km=42&sort=fit_score'
        )
        assert resp.status_code == 200
        races = resp.get_json()['races']
        # Turin marathon (exact distance + 0 km away) ranks first
        assert races[0]['name'] == 'Turin Marathon'
        assert races[0]['distance_from_base_km'] is not None
        assert races[0]['fit_score'] is not None
        assert races[0]['fit_score'] >= races[-1]['fit_score']


class TestRaceDetail:
    def test_404_when_missing(self, client):
        resp = client.get('/api/races/9999')
        assert resp.status_code == 404

    def test_returns_full_dict(self, client, seeded_races):
        resp = client.get(f'/api/races/{seeded_races[0]}')
        assert resp.status_code == 200
        race = resp.get_json()['race']
        assert race['name'] == 'Turin Marathon'
        assert race['country'] == 'IT'

    def test_by_slug_works(self, client, seeded_races):
        resp = client.get('/api/races/by-slug/r2')
        assert resp.status_code == 200
        assert resp.get_json()['race']['name'] == 'Susa Trail'


# ---------------------------------------------------------------------------
# POST /api/races/<id>/plan
# ---------------------------------------------------------------------------

class TestAddRaceToPlan:
    def test_requires_auth(self, client, seeded_races):
        resp = client.post(f'/api/races/{seeded_races[0]}/plan',
                           json={'priority': 'A'})
        assert resp.status_code == 401

    def test_validates_priority(self, app, client, seeded_races):
        user_id = _make_user(app)
        _login(client, app, user_id)
        resp = client.post(f'/api/races/{seeded_races[0]}/plan',
                           json={'priority': 'Z'})
        assert resp.status_code == 400

    def test_creates_plan_with_priority_and_default_weeks(
            self, app, client, seeded_races):
        user_id = _make_user(app)
        _login(client, app, user_id)
        resp = client.post(f'/api/races/{seeded_races[1]}/plan',
                           json={'priority': 'A'})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['created'] is True
        assert body['plan']['race_priority'] == 'A'
        assert body['plan']['race_id'] == seeded_races[1]
        assert len(body['plan']['weeks']) == 12  # default for A
        with app.app_context():
            plans = TrainingPlan.query.filter_by(user_id=user_id).all()
            assert len(plans) == 1

    def test_idempotent_second_call_updates_priority(
            self, app, client, seeded_races):
        user_id = _make_user(app)
        _login(client, app, user_id)
        first = client.post(f'/api/races/{seeded_races[1]}/plan',
                            json={'priority': 'B'})
        assert first.status_code == 201
        second = client.post(f'/api/races/{seeded_races[1]}/plan',
                             json={'priority': 'A'})
        assert second.status_code == 200
        body = second.get_json()
        assert body['created'] is False
        assert body['plan']['race_priority'] == 'A'
        with app.app_context():
            assert TrainingPlan.query.filter_by(user_id=user_id).count() == 1

    def test_404_for_unknown_race(self, app, client):
        user_id = _make_user(app)
        _login(client, app, user_id)
        resp = client.post('/api/races/9999/plan', json={'priority': 'A'})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/races/me/preferences
# ---------------------------------------------------------------------------

class TestPreferences:
    def test_requires_auth(self, client):
        assert client.get('/api/races/me/preferences').status_code == 401

    def test_returns_training_base(self, app, client):
        user_id = _make_user(app)
        _login(client, app, user_id)
        resp = client.get('/api/races/me/preferences')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['training_base_name'] == 'Turin'
        assert body['training_travel_radius_km'] == 120

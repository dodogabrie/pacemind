"""Tests for the race brief PDF builder + endpoint gating."""

from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import User, UserSubscription
from services.race_brief_pdf import render_race_brief_pdf


SAMPLE_BRIEF = {
    'route': {'distance_km': 172.4, 'elevation_gain_m': 9800},
    'terrain': {
        'summary': {'rock': 45.0, 'gravel': 35.0, 'asphalt': 20.0},
        'description': 'Mostly technical alpine terrain with rocky high passes.',
    },
    'weather': {
        'description': 'Cool 8 deg C with light wind, clear',
        'weather_factor': 0.97,
    },
    'training_status': {
        'form': 'fresh',
        'tsb': 18,
        'interpretation': 'You are well rested and primed for race day.',
    },
    'prediction': {
        'total_time_formatted': '44:18:08',
        'effort': 'race',
        'tier': 'TIER_1_PHYSICS',
        'confidence_interval': {'lower_formatted': '38:59:10', 'upper_formatted': '49:37:07'},
    },
    'key_challenges': [
        'Steep climb (22%) at km 31.4',
        'Steep descent (-19%) at km 47.8',
        'Steep climb (18%) at km 88.0',
    ],
    'gpx_id': 1,
    'race_date': '2026-08-29',
}


# ---------- pure render tests ----------

def test_render_returns_valid_pdf_bytes():
    data = render_race_brief_pdf(SAMPLE_BRIEF, route_name='UTMB Pyramides 2026')
    assert isinstance(data, bytes)
    assert data.startswith(b'%PDF-')
    assert len(data) > 500  # not an empty stub


def test_render_handles_missing_optional_fields():
    """Brief with empty terrain/weather/challenges must still render."""
    minimal = {
        'route': {'distance_km': 10, 'elevation_gain_m': 200},
        'terrain': {'summary': {}, 'description': None},
        'weather': {'description': None, 'weather_factor': 1.0},
        'training_status': {'form': 'unknown', 'tsb': 0, 'interpretation': None},
        'prediction': {
            'total_time_formatted': '01:00:00',
            'effort': 'training',
            'tier': 'TIER_1_PHYSICS',
            'confidence_interval': None,
        },
        'key_challenges': [],
        'gpx_id': 99,
        'race_date': '2026-01-01',
    }
    data = render_race_brief_pdf(minimal, route_name='Tiny test')
    assert data.startswith(b'%PDF-')


def test_render_strips_non_latin1_to_avoid_fpdf_crash():
    """Brief with em-dash / emoji should not raise."""
    brief = dict(SAMPLE_BRIEF)
    brief['terrain'] = dict(brief['terrain'])
    brief['terrain']['description'] = 'Steep — alpine \U0001F3D4 with technical rock'
    data = render_race_brief_pdf(brief, route_name='Mont Blanc — 2026')
    assert data.startswith(b'%PDF-')


# ---------- endpoint gating ----------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')  # bypass dev-mode short-circuit
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    app.config['ENV'] = 'production'
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def free_user(app):
    with app.app_context():
        u = User(strava_user_id=1, strava_username='free')
        db.session.add(u)
        db.session.commit()
        sub = UserSubscription(user_id=u.id, plan='free', status='active')
        db.session.add(sub)
        db.session.commit()
        return u.id


@pytest.fixture
def premium_user(app):
    with app.app_context():
        u = User(strava_user_id=2, strava_username='premium')
        db.session.add(u)
        db.session.commit()
        sub = UserSubscription(user_id=u.id, plan='premium_monthly', status='active')
        db.session.add(sub)
        db.session.commit()
        return u.id


def _login(client, app, user_id):
    """Set the JWT-bearing httpOnly cookie that get_current_user() reads."""
    from api.auth import generate_jwt
    with app.app_context():
        token = generate_jwt(user_id)
    client.set_cookie(key='jwt_token', value=token, domain='localhost')


def test_endpoint_requires_auth(app):
    client = app.test_client()
    resp = client.get('/api/agent/race-brief.pdf?gpx_id=1')
    assert resp.status_code == 401


def test_endpoint_blocks_free_tier(app, free_user):
    client = app.test_client()
    _login(client, app, free_user)
    resp = client.get('/api/agent/race-brief.pdf?gpx_id=1')
    assert resp.status_code == 402
    body = resp.get_json()
    assert body['feature'] == 'race_brief_pdf'
    assert body['upgrade_url']


def test_endpoint_validates_gpx_id(app, premium_user):
    client = app.test_client()
    _login(client, app, premium_user)
    resp = client.get('/api/agent/race-brief.pdf')  # missing gpx_id
    assert resp.status_code == 400
    resp = client.get('/api/agent/race-brief.pdf?gpx_id=abc')
    assert resp.status_code == 400


def test_endpoint_renders_pdf_for_premium(app, premium_user):
    client = app.test_client()
    _login(client, app, premium_user)
    with patch('services.race_brief_data.build_race_brief', return_value=SAMPLE_BRIEF):
        resp = client.get('/api/agent/race-brief.pdf?gpx_id=1')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data.startswith(b'%PDF-')
    assert 'attachment' in resp.headers.get('Content-Disposition', '')


def test_surface_mix_is_formatted_from_percentages():
    from services.race_brief_pdf import _format_pct
    # Same unit OSMTerrainService.get_terrain_summary returns (0-100).
    assert _format_pct({'rock': 45.0, 'gravel': 35.0, 'asphalt': 20.0}) == 'rock 45% / gravel 35% / asphalt 20%'

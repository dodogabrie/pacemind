"""Tests for the anonymous demo prediction endpoint."""

from pathlib import Path
from textwrap import dedent

import pytest

from app import create_app
from database import db


SAMPLE_GPX = dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
      <trk><name>tiny</name><trkseg>
        <trkpt lat="45.832" lon="6.864"><ele>1000</ele></trkpt>
        <trkpt lat="45.833" lon="6.865"><ele>1010</ele></trkpt>
        <trkpt lat="45.834" lon="6.866"><ele>1025</ele></trkpt>
        <trkpt lat="45.835" lon="6.867"><ele>1015</ele></trkpt>
        <trkpt lat="45.836" lon="6.868"><ele>1000</ele></trkpt>
      </trkseg></trk>
    </gpx>
""")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Build a Flask app whose demo dir contains a tiny test GPX."""
    demo_dir = tmp_path / 'data' / 'demo'
    demo_dir.mkdir(parents=True)
    (demo_dir / 'utmb-sample.gpx').write_text(SAMPLE_GPX)

    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    # Point the demo route loader at our temp dir.
    monkeypatch.setattr(app, 'root_path', str(tmp_path), raising=False)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_rate_buckets():
    """Demo endpoint uses an in-memory IP bucket; clear between tests."""
    from api import demo
    demo._rate_buckets.clear()


def test_routes_listing(client):
    resp = client.get('/api/demo/routes')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['routes'] == [{'id': 'utmb_pyramides', 'display_name': 'UTMB Pyramides (sample)'}]


def test_predict_returns_route_and_prediction(client):
    resp = client.post('/api/demo/predict', json={'route_id': 'utmb_pyramides'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['route']['id'] == 'utmb_pyramides'
    assert len(body['route']['points']) == 5
    pred = body['prediction']
    assert pred['total_time_seconds'] > 0
    assert pred['confidence_interval']['lower_seconds'] < pred['total_time_seconds']
    assert pred['confidence_interval']['upper_seconds'] > pred['total_time_seconds']
    assert pred['metadata']['tier'] == 'TIER_1_PHYSICS'


def test_predict_default_route_when_none_given(client):
    resp = client.post('/api/demo/predict', json={})
    assert resp.status_code == 200
    assert resp.get_json()['route']['id'] == 'utmb_pyramides'


def test_predict_rejects_unknown_route(client):
    resp = client.post('/api/demo/predict', json={'route_id': 'nope'})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'Unknown demo route'


def test_predict_does_not_require_auth(client):
    """Sanity: no JWT header / cookie -> still returns a prediction."""
    resp = client.post('/api/demo/predict', json={})
    assert resp.status_code == 200


def test_rate_limit_kicks_in_after_threshold(client, monkeypatch):
    """Cap is configured at 10 / hour by default."""
    from api import demo
    monkeypatch.setattr(demo, '_RATE_LIMIT_MAX', 3)

    for _ in range(3):
        ok = client.post('/api/demo/predict', json={})
        assert ok.status_code == 200
    blocked = client.post('/api/demo/predict', json={})
    assert blocked.status_code == 429
    assert 'rate limit' in blocked.get_json()['error'].lower()

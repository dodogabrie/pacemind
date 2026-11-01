"""Tests for the public waitlist endpoint and persistence."""

import pytest

from app import create_app
from database import db
from models import WaitlistSignup


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


def test_waitlist_persists_new_signup(app, client):
    resp = client.post('/api/billing/waitlist', json={
        'email': 'Caveman@Rock.IO',
        'plan': 'coach_team',
        'source': 'utm-test',
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {'status': 'joined', 'plan': 'coach_team', 'already_joined': False}

    with app.app_context():
        rows = WaitlistSignup.query.all()
        assert len(rows) == 1
        # Email is lower-cased, ip_hash + user-agent captured.
        assert rows[0].email == 'caveman@rock.io'
        assert rows[0].source == 'utm-test'
        assert rows[0].user_agent  # test client sets a default User-Agent
        assert rows[0].ip_hash and len(rows[0].ip_hash) == 32


def test_waitlist_dedupes_same_email_plan(app, client):
    client.post('/api/billing/waitlist', json={'email': 'a@b.c', 'plan': 'coach_team'})
    resp = client.post('/api/billing/waitlist', json={'email': 'a@b.c', 'plan': 'coach_team'})
    assert resp.status_code == 200
    assert resp.get_json()['already_joined'] is True

    with app.app_context():
        assert WaitlistSignup.query.count() == 1


def test_waitlist_allows_same_email_different_plan(app, client):
    client.post('/api/billing/waitlist', json={'email': 'a@b.c', 'plan': 'coach_team'})
    resp = client.post('/api/billing/waitlist', json={'email': 'a@b.c', 'plan': 'team'})
    assert resp.status_code == 200
    assert resp.get_json()['already_joined'] is False

    with app.app_context():
        assert WaitlistSignup.query.count() == 2


def test_waitlist_rejects_bad_email(client):
    resp = client.post('/api/billing/waitlist', json={'email': 'not-an-email', 'plan': 'coach_team'})
    assert resp.status_code == 400
    assert 'Valid email required' in resp.get_json()['error']


def test_waitlist_rejects_unknown_plan(client):
    resp = client.post('/api/billing/waitlist', json={'email': 'a@b.c', 'plan': 'gold-tier'})
    assert resp.status_code == 400
    assert 'Unknown plan' in resp.get_json()['error']

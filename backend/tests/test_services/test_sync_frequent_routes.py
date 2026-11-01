"""sync_frequent_routes: recurring activities become source='frequent' routes, once."""

from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from database import db
from models import Activity, User
from models.training_route import TrainingRoute
from services.route_suggestion_service import sync_frequent_routes


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


def _add(user_id, n, days_ago):
    latlng = [[45.0 + i * 1e-4, 9.0] for i in range(20)]
    a = Activity(
        user_id=user_id, strava_id=1000 + n, name=f'loop {n}', distance=5000.0,
        start_date=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    a.streams = {'latlng': latlng, 'altitude': [100.0 + i for i in range(20)],
                 'distance': [i * 250.0 for i in range(20)]}
    db.session.add(a)


def test_creates_once_and_is_idempotent(app):
    u = User(strava_user_id=1, strava_username='f')
    db.session.add(u)
    db.session.commit()
    _add(u.id, 1, 3)
    _add(u.id, 2, 10)
    db.session.commit()

    assert sync_frequent_routes(u.id) == 1
    assert sync_frequent_routes(u.id) == 0
    routes = TrainingRoute.query.filter_by(user_id=u.id).all()
    assert len(routes) == 1 and routes[0].source == 'frequent'

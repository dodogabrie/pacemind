"""GET /api/routes/<id>/gpx returns the saved route as a GPX attachment."""

import gpxpy
import pytest

from app import create_app
from database import db
from models import TrainingRoute, User


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


def test_gpx_download_owner_only(app):
    from api.auth import generate_jwt
    with app.app_context():
        owner, other = User(strava_user_id=1), User(strava_user_id=2)
        db.session.add_all([owner, other])
        db.session.flush()
        r = TrainingRoute(user_id=owner.id, name='Giro del Monte', route_data=[
            {'lat': 45.0, 'lon': 7.0, 'elevation': 300.0, 'distance': 0},
            {'lat': 45.001, 'lon': 7.001, 'elevation': 310.0, 'distance': 140},
        ])
        db.session.add(r)
        db.session.commit()
        rid, tokens = r.id, (generate_jwt(owner.id), generate_jwt(other.id))

    client = app.test_client()
    client.set_cookie(key='jwt_token', value=tokens[0], domain='localhost')
    resp = client.get(f'/api/routes/{rid}/gpx')
    assert resp.status_code == 200
    assert 'giro-del-monte.gpx' in resp.headers['Content-Disposition']
    pts = gpxpy.parse(resp.get_data(as_text=True)).tracks[0].segments[0].points
    assert [p.elevation for p in pts] == [300.0, 310.0]

    client.set_cookie(key='jwt_token', value=tokens[1], domain='localhost')
    assert client.get(f'/api/routes/{rid}/gpx').status_code == 404

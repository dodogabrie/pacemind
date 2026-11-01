"""Tests for waypoint management agent tools.

Tests suggest_waypoints, manage_annotations, and get_route_segments handlers.
"""

import pytest
from app import create_app
from database import db
from models import User, GPXFile
from models.prediction import Prediction


@pytest.fixture
def app():
    """Create test Flask app with in-memory SQLite."""
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
    """Create a test user."""
    with app.app_context():
        u = User(
            strava_user_id=99999,
            strava_username='waypoint_tester',
        )
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def gpx_file(app, user):
    """Create a GPX file with a simple 10km route."""
    with app.app_context():
        # 10km route with 200 points, some elevation
        points = []
        for i in range(201):
            dist = i * 50  # 50m spacing = 10km total
            elev = 500 + (50 if 2000 < dist < 4000 else 0)  # hill between 2-4km
            lat = 45.0 + i * 0.0001
            lon = 7.0 + i * 0.0001
            points.append({
                'distance': dist,
                'elevation': elev,
                'lat': lat,
                'lon': lon,
            })

        gpx = GPXFile(
            user_id=user,
            filename='test_route.gpx',
            original_filename='test_route.gpx',
            file_path='/tmp/test_route.gpx',
            data={'points': points},
        )
        db.session.add(gpx)
        db.session.commit()
        return gpx.id


@pytest.fixture
def prediction(app, user, gpx_file):
    """Create a prediction with no annotations."""
    with app.app_context():
        pred = Prediction(
            user_id=user,
            gpx_file_id=gpx_file,
            flat_pace=5.0,
            total_time_seconds=3600,
            predicted_segments=[],
            annotations={'annotations': []},
        )
        db.session.add(pred)
        db.session.commit()
        return pred.id


class TestSuggestWaypoints:
    """Test suggest_waypoints handler."""

    def test_suggest_waypoints_valid(self, app, user, gpx_file):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('suggest_waypoints', {
                'gpx_id': gpx_file,
                'waypoints': [
                    {'distance_km': 3.0, 'type': 'aid_station', 'label': 'AS1', 'reason': 'Mid-route'},
                    {'distance_km': 7.0, 'type': 'water', 'label': 'Water 1'},
                ]
            }, user)

            assert 'error' not in result
            assert result['count'] == 2
            suggestions = result['suggested_annotations']
            assert len(suggestions) == 2

            # Check enrichment
            assert suggestions[0]['lat'] is not None
            assert suggestions[0]['lon'] is not None
            assert suggestions[0]['type'] == 'aid_station'
            assert suggestions[0]['stop_time_seconds'] == 60  # default
            assert suggestions[1]['type'] == 'water'
            assert suggestions[1]['stop_time_seconds'] == 30  # default

    def test_suggest_waypoints_out_of_bounds(self, app, user, gpx_file):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('suggest_waypoints', {
                'gpx_id': gpx_file,
                'waypoints': [
                    {'distance_km': 3.0, 'type': 'aid_station', 'label': 'Valid'},
                    {'distance_km': 99.0, 'type': 'water', 'label': 'Too far'},
                ]
            }, user)

            assert 'error' not in result
            assert result['count'] == 1  # only valid one

    def test_suggest_waypoints_invalid_type(self, app, user, gpx_file):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('suggest_waypoints', {
                'gpx_id': gpx_file,
                'waypoints': [
                    {'distance_km': 3.0, 'type': 'invalid_type', 'label': 'Bad'},
                ]
            }, user)

            assert 'error' not in result
            assert result['count'] == 0  # invalid type skipped


class TestManageAnnotations:
    """Test manage_annotations handler."""

    def test_manage_annotations_list(self, app, user, prediction):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'list',
            }, user)

            assert result['success'] is True
            assert result['action'] == 'list'
            assert result['annotations'] == []

    def test_manage_annotations_add(self, app, user, prediction):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'add',
                'annotation': {
                    'type': 'aid_station',
                    'distance_km': 5.0,
                    'label': 'Aid Station 1',
                    'stop_time_seconds': 90,
                },
            }, user)

            assert result['success'] is True
            assert result['count'] == 1
            ann = result['annotations'][0]
            assert ann['type'] == 'aid_station'
            assert ann['label'] == 'Aid Station 1'
            assert ann['stop_time_seconds'] == 90
            assert ann['id']  # UUID generated
            assert ann['lat'] != 0  # lat/lon resolved

    def test_manage_annotations_remove(self, app, user, prediction):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            # First add
            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'add',
                'annotation': {
                    'type': 'checkpoint',
                    'distance_km': 8.0,
                    'label': 'CP1',
                },
            }, user)
            ann_id = result['annotations'][0]['id']

            # Then remove
            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'remove',
                'annotation_id': ann_id,
            }, user)

            assert result['success'] is True
            assert result['count'] == 0

    def test_manage_annotations_update(self, app, user, prediction):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            # Add
            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'add',
                'annotation': {
                    'type': 'water',
                    'distance_km': 4.0,
                    'label': 'Water Point',
                },
            }, user)
            ann_id = result['annotations'][0]['id']

            # Update
            result = handle_tool_call('manage_annotations', {
                'prediction_id': prediction,
                'action': 'update',
                'annotation_id': ann_id,
                'annotation': {
                    'label': 'Water Station A',
                    'stop_time_seconds': 45,
                },
            }, user)

            assert result['success'] is True
            updated = result['annotations'][0]
            assert updated['label'] == 'Water Station A'
            assert updated['stop_time_seconds'] == 45


class TestGetRouteSegments:
    """Test get_route_segments handler."""

    def test_get_route_segments(self, app, user, gpx_file):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('get_route_segments', {
                'gpx_id': gpx_file,
            }, user)

            assert 'error' not in result
            assert result['total_distance_km'] == 10.0
            assert result['n_segments'] > 0
            assert len(result['segments']) > 0

            # Check segment structure
            seg = result['segments'][0]
            assert 'distance_km' in seg
            assert 'elevation_m' in seg
            assert 'grade_pct' in seg
            assert 'cum_gain_m' in seg

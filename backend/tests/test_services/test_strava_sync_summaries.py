"""Strava sync keeps a summary row for every run, streams only for the top N."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import Activity, SyncStatus, User
from services.strava_sync_service import StravaSyncService
from services.training_load_service import TrainingLoadService


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


def _run(i, km, dplus, days_ago):
    start = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'id': 1000 + i, 'name': f'run {i}', 'type': 'Run', 'sport_type': 'TrailRun',
            'distance': km * 1000, 'total_elevation_gain': dplus, 'moving_time': km * 360,
            'elapsed_time': km * 400, 'start_date': start, 'start_date_local': start}


def test_all_runs_stored_streams_only_for_top_n(app):
    runs = [_run(1, 30, 1500, 3), _run(2, 10, 100, 2), _run(3, 12, 300, 1)]
    user = User(strava_user_id=42, strava_username='x', access_token='at',
                refresh_token='rt', expires_at=2**31)
    db.session.add(user)
    db.session.commit()
    status = SyncStatus(user_id=user.id, status='syncing')
    db.session.add(status)
    db.session.commit()

    service = StravaSyncService()
    service.MAX_STREAMS_PER_SYNC = 1
    with patch('services.strava_sync_service.StravaService') as strava, \
         patch('services.strava_sync_service.UserResidualService'):
        strava.return_value.get_valid_token.return_value = ('at', 'rt', 2**31)
        strava.return_value.fetch_activities.return_value = runs
        strava.return_value.download_streams.return_value = {
            'distance': [0, 30000], 'altitude': [100, 1600], 'time': [0, 10800]}
        downloaded = service._download_all_activities(user, status)

    assert len(downloaded) == 1
    rows = Activity.query.filter_by(user_id=user.id).all()
    assert len(rows) == 3
    assert [r.strava_id for r in rows if r.streams] == [1001]
    from repositories import ActivityRepository
    assert [a.strava_id for a in ActivityRepository().get_activities_with_streams(user.id)] == [1001]

    # Summary rows count towards load with the provider's D+: 10+1 + 12+3 = 26
    daily = TrainingLoadService()._compute_daily_load(
        [r for r in rows if not r.streams], datetime.now(timezone.utc).replace(tzinfo=None))
    assert round(sum(daily.values())) == 26


def test_reload_button_endpoint(app):
    from api.auth import generate_jwt
    client = app.test_client()
    no_strava = User(email='mail@runner.io', auth_provider='email')
    strava = User(strava_user_id=43, strava_username='y', access_token='at',
                  refresh_token='rt', expires_at=2**31)
    db.session.add_all([no_strava, strava])
    db.session.commit()

    client.set_cookie(key='jwt_token', value=generate_jwt(no_strava.id), domain='localhost')
    assert client.post('/api/strava/sync').status_code == 400

    client.set_cookie(key='jwt_token', value=generate_jwt(strava.id), domain='localhost')
    with patch('api.strava.StravaSyncService') as sync:
        assert client.post('/api/strava/sync').status_code == 202
        sync.return_value.sync_user_async.assert_called_once_with(strava.id, full=True)
        # Double click while the first one runs: refused, nothing started.
        assert client.post('/api/strava/sync').status_code == 409
        assert sync.return_value.sync_user_async.call_count == 1

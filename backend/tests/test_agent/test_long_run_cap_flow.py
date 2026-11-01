"""Tests for the long_run_cap_below_race_target conflict gate and the
raise_long_run_cap / search_tuneup_races tools.
"""

from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import User
from models.user_training_preferences import UserTrainingPreferences
from services.agent.tool_handlers.training import (
    _handle_generate_full_plan,
    _handle_raise_long_run_cap,
    _handle_search_tuneup_races,
)


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
def user_with_cap(app):
    with app.app_context():
        u = User(strava_user_id=42, strava_username='runner')
        u.training_base_lat = 45.0
        u.training_base_lon = 7.0
        u.training_base_name = 'Turin'
        db.session.add(u)
        db.session.commit()
        # User.training_travel_radius_km has a column-level default of 30,
        # which SQLAlchemy applies on INSERT even if we set it to None on the
        # instance. Force it back to NULL post-commit so these tests exercise
        # the "no saved preference -> universal 100 km default" code path.
        u.training_travel_radius_km = None
        db.session.commit()
        prefs = UserTrainingPreferences(
            user_id=u.id,
            max_weekly_km=80,
            max_long_run_km=40,
            terrain_profile='mountain',
            terrain_profile_source='user',
        )
        db.session.add(prefs)
        db.session.commit()
        return u.id


def _gen_input():
    return {
        'total_weeks': 12,
        'race_distance_km': 80,
        'race_elevation_m': 4000,
        'race_date': '2026-07-15',
        'athlete_weekly_km': 60,
        'athlete_weekly_elev': 1500,
        'athlete_longest_run_km': 35,
        'athlete_category': 'cat_2',
        'long_run_day': 'Sunday',
        'rest_days': [],
    }


class TestLongRunCapGate:
    def test_gate_triggers_when_cap_below_target(self, app, user_with_cap):
        with app.app_context():
            result = _handle_generate_full_plan(_gen_input(), user_with_cap)
            assert result.get('requires_user_decision') is True
            assert result['conflict'] == 'long_run_cap_below_race_target'
            assert result['user_cap_km'] == 40
            assert 55 <= result['race_target_km'] <= 65
            assert set(result['options']) == {'raise_cap', 'accept_compromise', 'find_tuneup_race'}

    def test_gate_skipped_when_acknowledged(self, app, user_with_cap):
        with app.app_context():
            inp = _gen_input()
            inp['acknowledge_long_run_cap'] = True
            result = _handle_generate_full_plan(inp, user_with_cap)
            # Should proceed past the gate (may still error in engine for other
            # reasons in a stripped test env, but NOT with the conflict shape).
            assert result.get('conflict') != 'long_run_cap_below_race_target'

    def test_no_gate_when_target_close_to_cap(self, app):
        with app.app_context():
            u = User(strava_user_id=43, strava_username='r2')
            db.session.add(u)
            db.session.commit()
            prefs = UserTrainingPreferences(
                user_id=u.id,
                max_weekly_km=60,
                max_long_run_km=32,
                terrain_profile='rolling_hills',
                terrain_profile_source='user',
            )
            db.session.add(prefs)
            db.session.commit()
            inp = _gen_input()
            inp['race_distance_km'] = 42  # target ≈ 31.5 km, cap 32 → no gate
            inp['race_elevation_m'] = 800
            result = _handle_generate_full_plan(inp, u.id)
            assert result.get('conflict') != 'long_run_cap_below_race_target'


class TestRaiseLongRunCap:
    def test_updates_pref_within_range(self, app, user_with_cap):
        with app.app_context():
            result = _handle_raise_long_run_cap({'new_km': 60}, user_with_cap)
            assert result['status'] == 'updated'
            assert result['max_long_run_km'] == 60

    def test_rejects_out_of_range(self, app, user_with_cap):
        with app.app_context():
            assert 'error' in _handle_raise_long_run_cap({'new_km': 100}, user_with_cap)
            assert 'error' in _handle_raise_long_run_cap({'new_km': 4}, user_with_cap)

    def test_rejects_non_numeric(self, app, user_with_cap):
        with app.app_context():
            assert 'error' in _handle_raise_long_run_cap({'new_km': 'sixty'}, user_with_cap)


class TestSearchTuneupRaces:
    def test_returns_requires_location_when_no_training_base(self, app):
        with app.app_context():
            u = User(strava_user_id=99, strava_username='nobase')
            db.session.add(u)
            db.session.commit()
            result = _handle_search_tuneup_races({
                'target_distance_km': 60,
                'window_start': '2026-04-01',
                'window_end': '2026-06-15',
            }, u.id)
            assert result.get('requires_location') is True

    def test_uses_training_base_and_calls_provider(self, app, user_with_cap):
        with app.app_context():
            with patch('services.race_calendar_service.find_races') as m:
                m.return_value = [{
                    'name': 'Lago Maggiore Trail',
                    'date': '2026-05-30',
                    'location': 'Verbania',
                    'country': 'IT',
                    'distance_km': 58,
                    'elev_m': 2900,
                    'lat': 45.92,
                    'lon': 8.55,
                    'url': 'https://example.com/race',
                    'distance_from_base_km': 80.0,
                    'fit_score': 0.78,
                    'source': 'itra',
                }]
                result = _handle_search_tuneup_races({
                    'target_distance_km': 60,
                    'target_elev_m': 3000,
                    'window_start': '2026-04-01',
                    'window_end': '2026-06-15',
                }, user_with_cap)
                assert m.called
                kwargs = m.call_args.kwargs
                assert kwargs['lat'] == 45.0
                assert kwargs['lon'] == 7.0
                assert result['location_name'] == 'Turin'
                assert len(result['races']) == 1
                assert result['races'][0]['fit_score'] == 0.78

    def test_provider_failure_returns_error_marker(self, app, user_with_cap):
        with app.app_context():
            with patch('services.race_calendar_service.find_races',
                       side_effect=RuntimeError('boom')):
                result = _handle_search_tuneup_races({
                    'target_distance_km': 60,
                    'window_start': '2026-04-01',
                    'window_end': '2026-06-15',
                }, user_with_cap)
                assert result.get('error') == 'calendar_unavailable'
                assert result['races'] == []

    def test_max_travel_km_override_is_forwarded(self, app, user_with_cap):
        with app.app_context():
            with patch('services.race_calendar_service.find_races') as m:
                m.return_value = []
                _handle_search_tuneup_races({
                    'target_distance_km': 60,
                    'window_start': '2026-04-01',
                    'window_end': '2026-06-15',
                    'max_travel_km': 250,
                }, user_with_cap)
                kwargs = m.call_args.kwargs
                assert kwargs['radius_km'] == 250.0

    def test_max_travel_km_falls_back_when_invalid(self, app, user_with_cap):
        with app.app_context():
            with patch('services.race_calendar_service.find_races') as m:
                m.return_value = []
                _handle_search_tuneup_races({
                    'target_distance_km': 60,
                    'window_start': '2026-04-01',
                    'window_end': '2026-06-15',
                    'max_travel_km': 'lots',
                }, user_with_cap)
                kwargs = m.call_args.kwargs
                # falls back to user.training_travel_radius_km (None) → default 100
                assert kwargs['radius_km'] == 100

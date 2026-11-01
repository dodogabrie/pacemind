"""Tests for agent tool handlers.

Uses Flask app context and in-memory SQLite for integration testing.
"""

import pytest
from app import create_app
from database import db
from models import User, GPXFile, UserLearnedParams
from models.agent_param_snapshot import AgentParamSnapshot
from config.hybrid_config import DEFAULT_PARAMS


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
            strava_user_id=12345,
            strava_username='test_runner',
        )
        db.session.add(u)
        db.session.commit()
        return u.id


class TestGetCurrentParams:
    """Test get_current_params handler."""

    def test_returns_defaults_when_no_learned_params(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call
            result = handle_tool_call('get_current_params', {}, user)

            assert result['source'] == 'defaults'
            assert result['params']['v_flat'] == DEFAULT_PARAMS['v_flat']
            assert result['manually_adjusted'] is False

    def test_returns_learned_params(self, app, user):
        with app.app_context():
            # Create learned params
            params = UserLearnedParams(
                user_id=user,
                v_flat=3.5,
                k_up=1.1,
                k_tech=1.05,
                fatigue_alpha=0.25,
                n_activities_used=10,
            )
            db.session.add(params)
            db.session.commit()

            from services.agent.tool_handlers import handle_tool_call
            result = handle_tool_call('get_current_params', {}, user)

            assert result['source'] == 'learned'
            assert result['params']['v_flat'] == 3.5
            assert result['params']['k_up'] == 1.1


class TestAdjustParams:
    """Test adjust_params handler."""

    def test_adjust_creates_snapshot_and_updates(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('adjust_params', {
                'adjustments': {'v_flat': 3.3, 'k_up': 1.1},
                'reason': 'Test adjustment'
            }, user)

            assert 'error' not in result
            assert result['new_params']['v_flat'] == 3.3
            assert result['new_params']['k_up'] == 1.1

            # Verify snapshot was created
            snapshot = AgentParamSnapshot.get_latest(user)
            assert snapshot is not None
            assert snapshot.action == 'adjust_params'

            # Verify manually_adjusted flag
            record = UserLearnedParams.query.filter_by(user_id=user).first()
            assert record.manually_adjusted is True

    def test_adjust_respects_bounds(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('adjust_params', {
                'adjustments': {'v_flat': 100.0},
                'reason': 'Extreme value'
            }, user)

            assert 'error' not in result
            assert result['new_params']['v_flat'] <= 5.0  # Max bound

    def test_empty_adjustments_returns_error(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('adjust_params', {
                'adjustments': {},
                'reason': 'Nothing'
            }, user)

            assert 'error' in result


class TestRollbackParams:
    """Test rollback_params handler."""

    def test_rollback_restores_previous_params(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            # First, adjust params (creates snapshot of defaults)
            handle_tool_call('adjust_params', {
                'adjustments': {'v_flat': 3.8},
                'reason': 'Make faster'
            }, user)

            # Verify adjustment took effect
            record = UserLearnedParams.query.filter_by(user_id=user).first()
            assert record.v_flat == 3.8

            # Now rollback
            result = handle_tool_call('rollback_params', {}, user)

            assert 'error' not in result
            assert result['restored_params']['v_flat'] == DEFAULT_PARAMS['v_flat']

    def test_rollback_with_no_snapshots(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call

            result = handle_tool_call('rollback_params', {}, user)
            assert 'error' in result
            assert 'No snapshots' in result['error']


class TestListGpxRoutes:
    """Test list_gpx_routes handler."""

    def test_returns_empty_when_no_routes(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call
            result = handle_tool_call('list_gpx_routes', {}, user)
            assert result['total'] == 0
            assert result['routes'] == []

    def test_returns_routes(self, app, user):
        with app.app_context():
            gpx = GPXFile(
                user_id=user,
                filename='test_route.gpx',
                original_filename='test_route.gpx',
                file_path='/tmp/test_route.gpx',
                data={'points': [
                    {'distance': 0, 'elevation': 100},
                    {'distance': 10000, 'elevation': 500},
                ]},
            )
            db.session.add(gpx)
            db.session.commit()

            from services.agent.tool_handlers import handle_tool_call
            result = handle_tool_call('list_gpx_routes', {}, user)

            assert result['total'] == 1
            assert result['routes'][0]['filename'] == 'test_route.gpx'
            assert result['routes'][0]['distance_km'] == 10.0


class TestWeekQualityValidation:
    """Test _assess_week_quality and its integration into _validate_single_week."""

    def test_complete_week_no_warnings(self):
        """A week with long_run + intervals should produce no quality warnings."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'intervals'},
            {'workout_type': 'easy'},
            {'workout_type': 'long_run'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 1, 'Build')
        assert warnings == []

    def test_missing_long_run_warning(self):
        """A week without a long run should warn."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'intervals'},
            {'workout_type': 'easy'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 3, 'Build')
        assert len(warnings) == 1
        assert 'long run' in warnings[0].lower()
        assert 'Week 3' in warnings[0]

    def test_missing_speed_work_warning(self):
        """A week without any speed/intensity session should warn."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'long_run'},
            {'workout_type': 'easy'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 2, 'Base')
        assert len(warnings) == 1
        assert 'speed' in warnings[0].lower() or 'intensity' in warnings[0].lower()

    def test_missing_both_warns_twice(self):
        """A week with only easy/rest should produce two warnings."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'easy'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 1, 'General')
        assert len(warnings) == 2

    def test_recovery_week_no_warnings_for_missing_key_workouts(self):
        """Recovery weeks should NOT warn about missing long run or speed work."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'recovery'},
            {'workout_type': 'rest'},
        ]
        for theme in ['Recovery', 'recovery week', 'Deload']:
            warnings = _assess_week_quality(days, 4, theme)
            assert warnings == [], f"Unexpected warnings for theme '{theme}': {warnings}"

    def test_recovery_week_warns_about_intensity(self):
        """Recovery weeks with high-intensity workouts should warn."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'intervals'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 4, 'Recovery')
        assert len(warnings) == 1
        assert 'intervals' in warnings[0].lower()
        assert 'Recovery' in warnings[0]

    def test_taper_week_treated_as_recovery(self):
        """Taper weeks should be treated like recovery weeks."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'easy'},
            {'workout_type': 'easy'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 8, 'Pre-race taper')
        assert warnings == []

    def test_tempo_counts_as_speed_work(self):
        """Tempo should satisfy the speed/intensity requirement."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'tempo'},
            {'workout_type': 'long_run'},
            {'workout_type': 'rest'},
        ]
        warnings = _assess_week_quality(days, 1, 'Build')
        assert warnings == []

    def test_hill_repeats_count_as_speed_work(self):
        """Hill repeats should satisfy the speed/intensity requirement."""
        from services.agent.tool_handlers import _assess_week_quality
        days = [
            {'workout_type': 'hill_repeats'},
            {'workout_type': 'long_run'},
            {'workout_type': 'easy'},
        ]
        warnings = _assess_week_quality(days, 1, 'Peak')
        assert warnings == []

    def test_validate_single_week_includes_quality_warnings(self, app):
        """_validate_single_week should include quality_warnings in output."""
        with app.app_context():
            from services.agent.tool_handlers import _validate_single_week
            result = _validate_single_week({
                'week_number': 1,
                'theme': 'Build',
                'days': [
                    {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 8},
                    {'day': 'Wednesday', 'workout_type': 'easy', 'distance_km': 10},
                    {'day': 'Friday', 'workout_type': 'rest'},
                ],
            })
            assert result['valid'] is True
            assert result['quality_warnings'] is not None
            assert len(result['quality_warnings']) == 2  # missing long_run + speed

    def test_validate_single_week_no_warnings_for_complete(self, app):
        """_validate_single_week should return None quality_warnings for complete weeks."""
        with app.app_context():
            from services.agent.tool_handlers import _validate_single_week
            result = _validate_single_week({
                'week_number': 1,
                'theme': 'Build',
                'days': [
                    {'day': 'Monday', 'workout_type': 'easy', 'distance_km': 8},
                    {'day': 'Wednesday', 'workout_type': 'intervals', 'distance_km': 10},
                    {'day': 'Saturday', 'workout_type': 'long_run', 'distance_km': 20},
                    {'day': 'Sunday', 'workout_type': 'rest'},
                ],
            })
            assert result['valid'] is True
            assert result['quality_warnings'] is None


class TestEditImpactAssessment:
    """Test _assess_edit_impact for evaluating training plan modifications."""

    def test_removing_long_run_high_impact(self):
        """Replacing long_run with rest should be high severity."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Saturday': {'workout_type': 'long_run'},
            'Sunday': {'workout_type': 'rest'},
        }
        after = {
            'Saturday': {'workout_type': 'rest'},
            'Sunday': {'workout_type': 'rest'},
        }
        impact = _assess_edit_impact(before, after, 3, 'Build')
        assert impact['severity'] == 'high'
        assert len(impact['warnings']) > 0
        assert any('long run' in w.lower() for w in impact['warnings'])
        assert len(impact['suggestions']) > 0

    def test_removing_intervals_high_impact(self):
        """Replacing intervals with easy should be high severity."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Tuesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Tuesday': {'workout_type': 'easy'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 2, 'Build')
        assert impact['severity'] == 'high'
        assert any('interval' in w.lower() or 'speed' in w.lower()
                    for w in impact['warnings'])

    def test_removing_easy_run_low_impact(self):
        """Replacing easy with rest should be low severity."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Monday': {'workout_type': 'easy'},
            'Wednesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Monday': {'workout_type': 'rest'},
            'Wednesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 1, 'Build')
        assert impact['severity'] == 'low'

    def test_replacing_intervals_with_tempo_no_warning(self):
        """Swapping one speed type for another should not produce key workout warnings."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Tuesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Tuesday': {'workout_type': 'tempo'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 1, 'Build')
        assert impact['severity'] == 'low'
        assert impact['removed_key_workouts'] is None

    def test_removing_only_speed_session_warns_quality(self):
        """Removing the only speed session should trigger quality warning."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Tuesday': {'workout_type': 'tempo'},
            'Thursday': {'workout_type': 'easy'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Tuesday': {'workout_type': 'easy'},
            'Thursday': {'workout_type': 'easy'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 2, 'Build')
        # Should have warnings about removing tempo AND quality warning about no speed work
        assert len(impact['warnings']) >= 2
        assert any('speed' in w.lower() or 'intensity' in w.lower()
                    for w in impact['warnings'])

    def test_no_changes_low_impact(self):
        """No workout type changes should be low severity with no warnings."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Tuesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Tuesday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 1, 'Build')
        assert impact['severity'] == 'low'
        assert impact['warnings'] == []

    def test_removing_vert_session_medium_impact(self):
        """Removing a vert_session (key but not high-impact) should be medium."""
        from services.agent.tool_handlers import _assess_edit_impact
        before = {
            'Tuesday': {'workout_type': 'vert_session'},
            'Thursday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        after = {
            'Tuesday': {'workout_type': 'easy'},
            'Thursday': {'workout_type': 'intervals'},
            'Saturday': {'workout_type': 'long_run'},
        }
        impact = _assess_edit_impact(before, after, 2, 'Build')
        assert impact['severity'] == 'medium'


class TestUnknownTool:
    """Test handling of unknown tool names."""

    def test_unknown_tool_returns_error(self, app, user):
        with app.app_context():
            from services.agent.tool_handlers import handle_tool_call
            result = handle_tool_call('nonexistent_tool', {}, user)
            assert 'error' in result
            assert 'Unknown tool' in result['error']

"""Tests for agent service (Claude API loop with mocking)."""

import json
import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from database import db
from models import User


@pytest.fixture
def app():
    """Create test Flask app."""
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
    with app.app_context():
        u = User(strava_user_id=99999, strava_username='agent_test')
        db.session.add(u)
        db.session.commit()
        return u.id


def _make_text_response(text):
    """Create a mock Claude response with text content only."""
    mock_block = MagicMock()
    mock_block.type = 'text'
    mock_block.text = text

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = 'end_turn'
    return mock_response


def _make_tool_use_response(tool_name, tool_input, tool_id='toolu_01'):
    """Create a mock Claude response with a tool_use block."""
    mock_block = MagicMock()
    mock_block.type = 'tool_use'
    mock_block.name = tool_name
    mock_block.input = tool_input
    mock_block.id = tool_id

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.stop_reason = 'tool_use'
    return mock_response


class TestAgentChat:
    """Test the agent chat loop."""

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_simple_text_response(self, mock_get_client, app, user):
        """Agent returns text without tool use."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response(
            "Your parameters look good!"
        )
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            result = chat(user, "How are my parameters?", conversation_id='test-1')

            assert result['error'] is None
            assert result['response'] == "Your parameters look good!"
            assert result['tool_calls'] == []

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_tool_use_then_text(self, mock_get_client, app, user):
        """Agent calls a tool then responds with text."""
        mock_client = MagicMock()

        # First call: tool_use, second call: text
        mock_client.messages.create.side_effect = [
            _make_tool_use_response('get_current_params', {}),
            _make_text_response("Your flat speed is 3.0 m/s."),
        ]
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            result = chat(user, "What are my params?", conversation_id='test-2')

            assert result['error'] is None
            assert 'flat speed' in result['response']
            assert len(result['tool_calls']) == 1
            assert result['tool_calls'][0]['tool'] == 'get_current_params'

    @patch('config.agent_config.AGENT_API_KEY', '')
    def test_no_api_key_returns_error(self, app, user):
        """Missing API key should return clear error."""
        with app.app_context():
            from services.agent.agent_service import chat
            result = chat(user, "Hello")

            assert result['error'] is not None
            assert 'API_KEY' in result['error']

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_max_rounds_exceeded(self, mock_get_client, app, user):
        """Agent should stop after max tool rounds."""
        mock_client = MagicMock()

        # Always return tool_use (never text) to trigger max rounds
        mock_client.messages.create.return_value = _make_tool_use_response(
            'get_current_params', {}
        )
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            result = chat(user, "Loop forever", conversation_id='test-3')

            assert result['error'] == 'max_rounds_exceeded'
            assert len(result['tool_calls']) > 0


class TestAgentEndpoint:
    """Test the /api/agent/chat Flask endpoint."""

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_chat_endpoint(self, mock_get_client, app, user):
        """POST /api/agent/chat should return agent response."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_text_response("Hello!")
        mock_get_client.return_value = mock_client

        with app.app_context():
            # Mock get_current_user
            with patch('api.agent.get_current_user') as mock_auth:
                mock_user = MagicMock()
                mock_user.id = user
                mock_auth.return_value = mock_user

                client = app.test_client()
                resp = client.post('/api/agent/chat', json={'message': 'Hello'})

                assert resp.status_code == 200
                data = resp.get_json()
                assert data['response'] == 'Hello!'

    def test_chat_endpoint_requires_message(self, app, user):
        """POST without message should return 400."""
        with app.app_context():
            with patch('api.agent.get_current_user') as mock_auth:
                mock_user = MagicMock()
                mock_user.id = user
                mock_auth.return_value = mock_user

                client = app.test_client()
                resp = client.post('/api/agent/chat', json={})

                assert resp.status_code == 400

    def test_chat_endpoint_requires_auth(self, app):
        """POST without auth should return 401."""
        with app.app_context():
            with patch('api.agent.get_current_user', return_value=None):
                client = app.test_client()
                resp = client.post('/api/agent/chat', json={'message': 'Hello'})
                assert resp.status_code == 401

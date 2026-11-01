"""Chat history persistence — DB round-trip across separate chat() calls."""

import pytest
from unittest.mock import MagicMock, patch

from app import create_app
from database import db
from models import User, AgentConversation


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
def user(app):
    with app.app_context():
        u = User(strava_user_id=777, strava_username='persist_user')
        db.session.add(u)
        db.session.commit()
        return u.id


def _text_response(text):
    block = MagicMock()
    block.type = 'text'
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = 'end_turn'
    return resp


class TestConversationPersistence:
    """The in-memory cache of the old implementation lost history on restart.
    These tests lock in the new DB-backed behavior."""

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_conversation_is_persisted(self, mock_get_client, app, user):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response('Hi there!')
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            chat(user, 'hello', conversation_id='my-thread')

            row = AgentConversation.query.filter_by(
                user_id=user, conversation_id='my-thread'
            ).one()
            assert len(row.messages) == 2
            assert row.messages[0]['role'] == 'user'
            assert row.messages[0]['content'].endswith('hello') \
                or 'hello' in row.messages[0]['content']
            assert row.messages[1]['role'] == 'assistant'

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_second_call_resumes_from_db(self, mock_get_client, app, user):
        """Claude is invoked with prior turns on the second call."""
        import copy
        captured = []

        def _capture(**kwargs):
            # Deep-copy so later mutations of `messages` don't poison the snapshot
            captured.append(copy.deepcopy(kwargs.get('messages', [])))
            responses = iter([_text_response('first answer'), _text_response('second answer')])
            return next(responses) if len(captured) == 1 else _text_response('second answer')

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _capture
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            chat(user, 'first question', conversation_id='t-resume')
            chat(user, 'second question', conversation_id='t-resume')

            # First call: just the new user message
            assert len(captured[0]) == 1
            assert captured[0][0]['role'] == 'user'
            assert 'first question' in captured[0][0]['content']

            # Second call: user1, assistant1, user2
            assert len(captured[1]) == 3
            assert captured[1][0]['role'] == 'user'
            assert 'first question' in captured[1][0]['content']
            assert captured[1][1]['role'] == 'assistant'
            assert captured[1][2]['role'] == 'user'
            assert captured[1][2]['content'] == 'second question'

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_separate_conversation_ids_do_not_mix(self, mock_get_client, app, user):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _text_response('reply')
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            chat(user, 'thread A msg', conversation_id='conv-A')
            chat(user, 'thread B msg', conversation_id='conv-B')

            a = AgentConversation.query.filter_by(
                user_id=user, conversation_id='conv-A'
            ).one()
            b = AgentConversation.query.filter_by(
                user_id=user, conversation_id='conv-B'
            ).one()
            assert len(a.messages) == 2
            assert len(b.messages) == 2
            assert 'thread A' in a.messages[0]['content']
            assert 'thread B' in b.messages[0]['content']

    @patch('config.agent_config.AGENT_API_KEY', 'test-key')
    @patch('services.agent.agent_service._get_client')
    def test_context_prefix_applied_only_to_first_message(
        self, mock_get_client, app, user,
    ):
        """Prefix like '[Context: viewing GPX 5]' must not be repeated on turn 2."""
        import copy
        captured = []

        def _capture(**kwargs):
            captured.append(copy.deepcopy(kwargs.get('messages', [])))
            return _text_response('ok')

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _capture
        mock_get_client.return_value = mock_client

        with app.app_context():
            from services.agent.agent_service import chat
            chat(user, 'turn 1', conversation_id='t-ctx', gpx_id=5)
            chat(user, 'turn 2', conversation_id='t-ctx', gpx_id=5)

            # First user message has the [Context: ...] prefix
            assert '[Context:' in captured[0][0]['content']
            # Second user message (turn 2) is raw — no prefix re-applied
            assert captured[1][-1]['role'] == 'user'
            assert captured[1][-1]['content'] == 'turn 2'


class TestRepositoryOperations:
    def test_delete_for_user_clears_all(self, app, user):
        from repositories import AgentConversationRepository
        with app.app_context():
            repo = AgentConversationRepository()
            repo.save_messages(user, 'c1', [{'role': 'user', 'content': 'x'}])
            repo.save_messages(user, 'c2', [{'role': 'user', 'content': 'y'}])
            repo.commit()
            assert AgentConversation.query.filter_by(user_id=user).count() == 2

            deleted = repo.delete_for_user(user)
            repo.commit()
            assert deleted == 2
            assert AgentConversation.query.filter_by(user_id=user).count() == 0

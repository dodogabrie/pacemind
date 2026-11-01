"""MCP endpoint: auth, handshake, tool listing and a real tool call."""

import pytest

from app import create_app
from api.auth import generate_jwt
from database import db
from models import User


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


@pytest.fixture
def token(app, client):
    user = User(email='mcp@runner.io')
    db.session.add(user)
    db.session.commit()
    resp = client.post('/api/mcp/token', headers={'Authorization': f'Bearer {generate_jwt(user.id)}'})
    assert resp.status_code == 200
    return resp.get_json()['token']


def _rpc(client, token, method, params=None, msg_id=1):
    body = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
    if msg_id is not None:
        body['id'] = msg_id
    return client.post('/api/mcp', json=body, headers={'Authorization': f'Bearer {token}'})


def test_rejects_missing_token(client):
    resp = client.post('/api/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert resp.status_code == 401
    assert 'Bearer' in resp.headers['WWW-Authenticate']


def test_token_requires_login(client):
    assert client.post('/api/mcp/token').status_code == 401


def test_handshake_and_list(client, token):
    init = _rpc(client, token, 'initialize', {'protocolVersion': '2025-06-18'}).get_json()
    assert init['result']['serverInfo']['name'] == 'pacemind'
    assert init['result']['instructions']
    assert _rpc(client, token, 'notifications/initialized', msg_id=None).status_code == 202

    tools = _rpc(client, token, 'tools/list').get_json()['result']['tools']
    names = {t['name'] for t in tools}
    assert 'inspect_training_plan' in names
    assert 'start_onboarding_questionnaire' not in names
    assert all(t['inputSchema']['type'] == 'object' for t in tools)


def test_tool_call_and_unknowns(client, token):
    res = _rpc(client, token, 'tools/call', {'name': 'get_tier_status', 'arguments': {}}).get_json()
    assert res['result']['content'][0]['type'] == 'text'

    assert _rpc(client, token, 'tools/call', {'name': 'nope'}).get_json()['error']['code'] == -32602
    assert _rpc(client, token, 'bogus').get_json()['error']['code'] == -32601

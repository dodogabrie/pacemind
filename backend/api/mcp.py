"""MCP server: exposes the coach's tools to Claude, Codex and other MCP clients.

Streamable HTTP transport in its stateless form: every POST carries one
JSON-RPC message and gets a plain JSON reply, no SSE, no session id.
Auth is a Bearer token from POST /api/mcp/token.
"""

from datetime import datetime, timedelta, timezone

import jwt
from flask import Blueprint, current_app, jsonify, request

from api.auth import verify_jwt
from api.utils import get_current_user
from services.agent.prompts import SYSTEM_PROMPT
from services.agent.tools import AGENT_TOOLS

bp = Blueprint('mcp', __name__)

PROTOCOL_VERSION = '2025-06-18'
TOKEN_DAYS = 180
# Opens a modal in our web UI; meaningless to an external client.
_UI_ONLY = {'start_onboarding_questionnaire'}

_TOOLS = [
    {'name': t['name'], 'description': t['description'], 'inputSchema': t['input_schema']}
    for t in AGENT_TOOLS if t['name'] not in _UI_ONLY
]
_TOOL_NAMES = {t['name'] for t in _TOOLS}


@bp.route('/api/mcp/token', methods=['POST'])
def issue_token():
    """Long-lived token the user pastes into their MCP client config."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    # ponytail: no revocation list; rotating JWT_SECRET_KEY kills every token.
    # Add a token table when users need to revoke a single client.
    payload = {
        'user_id': user.id,
        'scope': 'mcp',
        'exp': datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS),
    }
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return jsonify({'token': token, 'expires_in_days': TOKEN_DAYS})


def _result(msg_id, result):
    return jsonify({'jsonrpc': '2.0', 'id': msg_id, 'result': result})


def _error(msg_id, code, message):
    return jsonify({'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}})


def _call_tool(name, args, user_id):
    import json
    from services.agent.agent_service import _execute_tool
    # Same path as the in-app chat: plan-gen quota and charging included.
    result, _ = _execute_tool(name, args, user_id, False, {})
    is_error = isinstance(result, dict) and 'error' in result
    return {
        'content': [{'type': 'text', 'text': json.dumps(result, default=str)}],
        'isError': is_error,
    }


@bp.route('/api/mcp', methods=['POST'])
def mcp():
    auth = request.headers.get('Authorization', '')
    user_id = verify_jwt(auth[7:]) if auth.startswith('Bearer ') else None
    if not user_id:
        resp = jsonify({'error': 'Missing or invalid Bearer token'})
        resp.headers['WWW-Authenticate'] = 'Bearer'
        return resp, 401

    msg = request.get_json(silent=True)
    if not isinstance(msg, dict):
        return _error(None, -32700, 'Parse error'), 400
    method, msg_id = msg.get('method'), msg.get('id')
    if msg_id is None:  # notification or response: nothing to answer
        return '', 202

    params = msg.get('params') or {}
    if method == 'initialize':
        return _result(msg_id, {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'pacemind', 'version': '1.0'},
            'instructions': SYSTEM_PROMPT,
        })
    if method == 'ping':
        return _result(msg_id, {})
    if method == 'tools/list':
        return _result(msg_id, {'tools': _TOOLS})
    if method == 'tools/call':
        name = params.get('name')
        if name not in _TOOL_NAMES:
            return _error(msg_id, -32602, f'Unknown tool: {name}')
        return _result(msg_id, _call_tool(name, params.get('arguments') or {}, user_id))
    return _error(msg_id, -32601, f'Method not found: {method}')

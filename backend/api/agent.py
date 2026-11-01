"""Agent API endpoint for LLM-powered prediction tuning."""

import os

from flask import Blueprint, request, jsonify, current_app, Response, stream_with_context
from api.utils import get_current_user
from repositories import (
    AgentConversationRepository,
    GPXFileRepository,
    SubscriptionRepository,
)
from config.hybrid_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('agent', __name__, url_prefix='/api/agent')

subscription_repo = SubscriptionRepository()
gpx_repo = GPXFileRepository()
conversation_repo = AgentConversationRepository()


def _user_message_text(content):
    """Extract plain text from a stored message content (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'text':
                parts.append(b.get('text', ''))
        return '\n'.join(parts)
    return ''


def _strip_context_prefix(text: str) -> str:
    if text.startswith('[Context:'):
        end = text.find(']')
        if end != -1:
            return text[end + 1:].lstrip()
    return text


def _serialize_conversation_summary(conv) -> dict:
    """Compact list-row payload (no full message blob)."""
    msgs = conv.messages or []
    user_count = sum(1 for m in msgs if isinstance(m, dict) and m.get('role') == 'user')
    return {
        'conversation_id': conv.conversation_id,
        'context_type': conv.context_type,
        'title': conv.title,
        'user_message_count': user_count,
        'created_at': conv.created_at.isoformat() if conv.created_at else None,
        'last_active_at': conv.last_active_at.isoformat() if conv.last_active_at else None,
    }


def _serialize_messages_for_ui(messages: list) -> list:
    """Convert stored Anthropic-shape messages into the simple
    {role, content, toolCalls} shape AgentChat.vue renders.

    Tool-result turns (role=user with content=[{type:tool_result,...}]) are
    dropped — those aren't user-authored. The first user message has its
    [Context: ...] prefix stripped so users don't see internal scaffolding.
    """
    out = []
    pending_tool_calls = []
    first_user_seen = False

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get('role')
        content = m.get('content')

        if role == 'user':
            # Skip tool_result-only turns; they're protocol, not user input.
            if isinstance(content, list) and content and all(
                isinstance(b, dict) and b.get('type') == 'tool_result' for b in content
            ):
                continue
            text = _user_message_text(content)
            if not first_user_seen:
                text = _strip_context_prefix(text)
                first_user_seen = True
            out.append({'role': 'user', 'content': text, 'toolCalls': []})
            continue

        if role == 'assistant':
            blocks = content if isinstance(content, list) else []
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text':
                    text_parts.append(b.get('text', ''))
                elif b.get('type') == 'tool_use':
                    pending_tool_calls.append({
                        'tool': b.get('name', ''),
                        'input': b.get('input', {}),
                        'result_summary': '',
                    })
            text = '\n'.join(p for p in text_parts if p)
            if text or pending_tool_calls:
                out.append({
                    'role': 'assistant',
                    'content': text,
                    'toolCalls': pending_tool_calls,
                })
                pending_tool_calls = []
    return out


@bp.route('/chat', methods=['POST'])
def chat():
    """Send a message to the prediction tuning agent.

    Body:
        {
            "message": "I'm a strong uphill runner, adjust my model",
            "conversation_id": "optional-session-id"
        }

    Returns:
        {
            "response": "I've increased your uphill coefficient (k_up) from 1.0 to 1.15...",
            "tool_calls": [
                {"tool": "get_current_params", "input": {}, "result_summary": "ok (params, source, ...)"},
                {"tool": "adjust_params", "input": {"adjustments": {"k_up": 1.15}}, "result_summary": "ok (...)"}
            ],
            "error": null
        }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    # Check agent message limits (free tier: 3/day, bypassed in dev mode)
    sub = subscription_repo.get_or_create(user.id)
    dev_mode = current_app.config.get('ENV') == 'development' or os.environ.get('FLASK_ENV') == 'development'
    if not dev_mode and not sub.can_use_agent:
        return jsonify({
            'error': 'Daily message limit reached',
            'agent_messages_remaining': 0,
            'upgrade_url': '/api/billing/checkout',
            'message': (
                f'You\'ve used all {sub.chat_daily_limit} agent messages for today. '
                'Upgrade to Premium for a higher daily cap.'
                if sub.is_premium
                else 'You\'ve used your 3 free agent messages today. Upgrade to Premium for a higher daily cap.'
            ),
        }), 429

    if not dev_mode and not sub.can_spend_tokens():
        return jsonify({
            'error': 'Daily AI usage limit reached',
            'tokens_remaining_today': sub.tokens_remaining_today(),
            'upgrade_url': '/api/billing/checkout',
            'message': (
                'You\'ve hit your daily AI usage cap. It resets tomorrow.'
                if sub.is_premium
                else 'You\'ve hit the free daily AI usage cap. Upgrade to Premium for a much higher cap.'
            ),
        }), 429

    data = request.get_json()
    if not data or not data.get('message'):
        return jsonify({'error': 'Message is required'}), 400

    message = data['message'].strip()
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    if len(message) > 2000:
        return jsonify({'error': 'Message too long (max 2000 characters)'}), 400

    conversation_id = data.get('conversation_id')
    gpx_id = data.get('gpx_id')
    prediction_id = data.get('prediction_id')
    plan_id = data.get('plan_id')
    context_type = data.get('context_type')

    try:
        from services.agent.agent_service import chat as agent_chat
        result = agent_chat(
            user_id=user.id,
            user_message=message,
            conversation_id=conversation_id,
            gpx_id=gpx_id,
            prediction_id=prediction_id,
            plan_id=plan_id,
            context_type=context_type,
        )

        # Track usage after successful response
        subscription_repo.increment_agent_usage(sub)
        usage = result.pop('_usage', None) or {}
        if usage:
            subscription_repo.record_token_usage(
                sub,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                cache_read_tokens=usage.get('cache_read_tokens', 0),
                cache_creation_tokens=usage.get('cache_creation_tokens', 0),
            )
        subscription_repo.commit()

        # Include remaining messages in response
        result['agent_messages_remaining'] = sub.agent_messages_remaining
        result['tokens_remaining_today'] = sub.tokens_remaining_today()

        return jsonify(result)

    except ImportError as e:
        logger.error(f"Agent dependency missing: {e}")
        return jsonify({'error': 'Agent not available. Install the anthropic package: pip install anthropic'}), 503

    except Exception as e:
        subscription_repo.rollback()
        logger.exception(f"Agent error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@bp.route('/chat/stream', methods=['POST'])
def chat_stream():
    """Streaming version of /chat that sends SSE events during tool execution.

    Same request body as /chat. Returns text/event-stream with events:
    - tool_start: {tool, label} — tool execution began
    - tool_end: {tool, result_summary} — tool execution finished
    - done: full result payload (same as /chat response)
    - error: {error} — something went wrong
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    sub = subscription_repo.get_or_create(user.id)
    dev_mode = current_app.config.get('ENV') == 'development' or os.environ.get('FLASK_ENV') == 'development'
    if not dev_mode and not sub.can_use_agent:
        return jsonify({
            'error': 'Daily message limit reached',
            'agent_messages_remaining': 0,
            'upgrade_url': '/api/billing/checkout',
            'message': (
                f'You\'ve used all {sub.chat_daily_limit} agent messages for today. '
                'Upgrade to Premium for a higher daily cap.'
                if sub.is_premium
                else 'You\'ve used your 3 free agent messages today. Upgrade to Premium for a higher daily cap.'
            ),
        }), 429

    if not dev_mode and not sub.can_spend_tokens():
        return jsonify({
            'error': 'Daily AI usage limit reached',
            'tokens_remaining_today': sub.tokens_remaining_today(),
            'upgrade_url': '/api/billing/checkout',
            'message': (
                'You\'ve hit your daily AI usage cap. It resets tomorrow.'
                if sub.is_premium
                else 'You\'ve hit the free daily AI usage cap. Upgrade to Premium for a much higher cap.'
            ),
        }), 429

    data = request.get_json()
    if not data or not data.get('message'):
        return jsonify({'error': 'Message is required'}), 400

    message = data['message'].strip()
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    if len(message) > 2000:
        return jsonify({'error': 'Message too long (max 2000 characters)'}), 400

    conversation_id = data.get('conversation_id')
    gpx_id = data.get('gpx_id')
    prediction_id = data.get('prediction_id')
    plan_id = data.get('plan_id')
    context_type = data.get('context_type')

    def generate():
        try:
            from services.agent.agent_service import chat_stream as agent_chat_stream
            done_emitted = False
            for event in agent_chat_stream(
                user_id=user.id,
                user_message=message,
                conversation_id=conversation_id,
                gpx_id=gpx_id,
                prediction_id=prediction_id,
                plan_id=plan_id,
                context_type=context_type,
            ):
                # Check if this is the done event to track usage
                if event.startswith('event: done\n'):
                    done_emitted = True
                    subscription_repo.increment_agent_usage(sub)
                    # Inject remaining + record token spend from done payload
                    import json
                    lines = event.split('\n')
                    for idx, line in enumerate(lines):
                        if line.startswith('data: '):
                            payload = json.loads(line[6:])
                            usage = payload.pop('_usage', None) or {}
                            if usage:
                                subscription_repo.record_token_usage(
                                    sub,
                                    input_tokens=usage.get('input_tokens', 0),
                                    output_tokens=usage.get('output_tokens', 0),
                                    cache_read_tokens=usage.get('cache_read_tokens', 0),
                                    cache_creation_tokens=usage.get('cache_creation_tokens', 0),
                                )
                            payload['agent_messages_remaining'] = sub.agent_messages_remaining
                            payload['tokens_remaining_today'] = sub.tokens_remaining_today()
                            lines[idx] = 'data: ' + json.dumps(payload)
                            break
                    subscription_repo.commit()
                    event = '\n'.join(lines)
                yield event

            if not done_emitted:
                subscription_repo.rollback()

        except ImportError as e:
            logger.error(f"Agent dependency missing: {e}")
            import json
            yield f"event: error\ndata: {json.dumps({'error': 'Agent not available'})}\n\n"
        except Exception as e:
            subscription_repo.rollback()
            logger.exception(f"Agent stream error: {e}")
            import json
            yield f"event: error\ndata: {json.dumps({'error': 'Internal server error'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/conversations', methods=['GET'])
def list_conversations():
    """List the current user's chat conversations.

    Query params:
        context (optional) — filter by context_type (e.g. 'training-plan')
        limit (optional, default 50)
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    context_type = request.args.get('context')
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50

    convs = conversation_repo.list_for_user(user.id, context_type=context_type, limit=limit)
    return jsonify({
        'conversations': [_serialize_conversation_summary(c) for c in convs],
    })


@bp.route('/conversations/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """Return a single conversation's UI-shaped messages so the chat can resume."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    conv = conversation_repo.get(user.id, conversation_id)
    if conv is None:
        return jsonify({'error': 'Not found'}), 404

    return jsonify({
        **_serialize_conversation_summary(conv),
        'messages': _serialize_messages_for_ui(conv.messages or []),
    })


@bp.route('/conversations/<conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    deleted = conversation_repo.delete_one(user.id, conversation_id)
    if not deleted:
        return jsonify({'error': 'Not found'}), 404
    conversation_repo.commit()
    return jsonify({'status': 'deleted'})


@bp.route('/race-brief.pdf', methods=['GET'])
def race_brief_pdf():
    """Download the pre-race brief as a PDF (Premium + Race Day Pass).

    Query params:
        gpx_id (int, required)
        race_date (YYYY-MM-DD, optional)
        effort (race|training|recovery, default race)
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    sub = subscription_repo.get_or_create(user.id)
    dev_mode = current_app.config.get('ENV') == 'development' or os.environ.get('FLASK_ENV') == 'development'
    # is_premium == True for premium_monthly, premium_yearly, and active race_day_pass
    if not dev_mode and not sub.is_premium:
        return jsonify({
            'error': 'Premium subscription required',
            'feature': 'race_brief_pdf',
            'upgrade_url': '/pricing',
        }), 402

    try:
        gpx_id = int(request.args.get('gpx_id', '0'))
    except (TypeError, ValueError):
        return jsonify({'error': 'gpx_id must be an integer'}), 400
    if not gpx_id:
        return jsonify({'error': 'gpx_id is required'}), 400

    race_date_str = request.args.get('race_date')
    effort = request.args.get('effort', 'race')
    if effort not in ('race', 'training', 'recovery'):
        return jsonify({'error': 'effort must be race, training, or recovery'}), 400

    try:
        from services.race_brief_data import build_race_brief
        from services.race_brief_pdf import render_race_brief_pdf

        brief = build_race_brief(
            user_id=user.id,
            gpx_id=gpx_id,
            race_date_str=race_date_str,
            effort=effort,
        )
        if 'error' in brief:
            return jsonify(brief), 400

        gpx_file = gpx_repo.get_user_file(gpx_id, user.id)
        route_name = (gpx_file.original_filename if gpx_file else None) or f"Race brief #{gpx_id}"
        if route_name.lower().endswith('.gpx'):
            route_name = route_name[:-4]

        pdf_bytes = render_race_brief_pdf(brief, route_name=route_name)

        safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in route_name)[:60]
        filename = f"race-brief-{safe_name}-{brief.get('race_date', 'undated')}.pdf"

        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Cache-Control': 'no-store',
            },
        )
    except Exception as e:
        logger.exception(f"Race brief PDF error: {e}")
        return jsonify({'error': 'Failed to render race brief'}), 500

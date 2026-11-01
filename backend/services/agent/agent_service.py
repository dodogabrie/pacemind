"""Agent service — manages the Claude tool-use loop.

Public entry points:
    chat(...)         — runs the loop and returns a dict
    chat_stream(...)  — runs the loop and yields SSE event strings

Both share a single internal generator (`_run_chat`) that owns the tool
loop: the streaming wrapper maps its yielded events to SSE, the blocking
wrapper drains them and keeps only the final payload.

Conversation history is persisted to Postgres via AgentConversationRepository
(table `agent_conversations`). Each `(user_id, conversation_id)` pair is one
row; messages survive restarts.
"""

import copy
import json
import time
from datetime import date
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from config.agent_config import (
    AGENT_MODEL,
    AGENT_MAX_TOKENS,
    AGENT_MAX_TOOL_ROUNDS,
    AGENT_FULL_PLAN_WEEK_STREAM_DELAY,
)
from config.hybrid_config import get_logger
from services.agent.knowledge_context import get_training_plan_knowledge
from services.agent.prompts import SYSTEM_PROMPT
from services.agent.tool_handlers import handle_tool_call
from services.agent.tools import AGENT_TOOLS, TOOL_DISPLAY_NAMES

logger = get_logger(__name__)


PLAN_GEN_TOOLS = {'generate_training_week', 'generate_full_plan'}


# ---------------------------------------------------------------------------
# Plan-generation quota (runs as a side-effect inside the tool loop)
# ---------------------------------------------------------------------------

def _plan_gen_quota_error(sub) -> Dict:
    """Synthetic tool error returned when the user is out of plan-gen budget.

    Fed back to Claude as the tool_result so the agent stops the generation
    loop and surfaces the limit to the user.
    """
    return {
        'error': 'plan_generation_limit_reached',
        'message': (
            f'You have used all {sub.plan_generation_period_limit} plan generations '
            f'for this period. Upgrade or wait until the next period to generate more.'
        ),
        'upgrade_url': '/api/billing/checkout',
        'plan_generations_remaining': 0,
        '_retry_hint': 'STOP retrying. Inform the user they reached the plan-generation quota.',
    }


def _check_plan_gen_quota(user_id: int, tool_name: str, already_charged: bool):
    """Return (allowed, subscription_or_None). Non-plan-gen tools always pass."""
    if tool_name not in PLAN_GEN_TOOLS or already_charged:
        return True, None
    try:
        from flask import has_app_context
        if not has_app_context():
            return True, None
        from repositories import SubscriptionRepository
        repo = SubscriptionRepository()
        sub = repo.get_or_create(user_id)
        return sub.can_generate_plan, sub
    except Exception:
        logger.exception('plan-gen quota check failed; allowing call')
        return True, None


def _charge_plan_gen(user_id: int) -> None:
    try:
        from flask import has_app_context
        if not has_app_context():
            return
        from repositories import SubscriptionRepository
        repo = SubscriptionRepository()
        sub = repo.get_or_create(user_id)
        sub.increment_plan_generation()
        repo.commit()
    except Exception:
        logger.exception('plan-gen counter increment failed')


# ---------------------------------------------------------------------------
# Anthropic client + tool list (with ephemeral prompt cache markers)
# ---------------------------------------------------------------------------

_CACHED_TOOLS_BY_CONTEXT: Dict[str, list] = {}

# Tools to drop per context, to shrink tool-schema input tokens (~15-25k total
# uncached). Each tool definition is ~300-700 tokens; on Haiku 4.5's 50k ITPM
# tier this matters because cache_read tokens still count against the rate
# limit at face value. Only exclude tools that are unambiguously irrelevant to
# the context — when unsure, keep the tool. The 'default' context (prediction
# / route analysis) keeps the full set.
_TOOLS_EXCLUDE_TRAINING_PLAN = frozenset({
    # Single-GPX prediction & calibration UI tools
    'run_prediction', 'compare_predictions',
    'get_current_params', 'adjust_params',
    'retrain_model', 'rollback_params',
    # Race-day execution tools
    'get_pacing_strategy', 'get_nutrition_estimate',
    'get_equipment_suggestion', 'get_race_briefing',
    'generate_race_report', 'get_race_report',
    # Annotation / segment-inspection tools
    'suggest_waypoints', 'manage_annotations', 'get_route_segments',
})

_TOOLS_EXCLUDE_RACE_DASHBOARD = frozenset({
    # Plan-creation / onboarding tools (plan already exists on this page)
    'generate_full_plan', 'generate_training_week', 'save_training_plan',
    'start_onboarding_questionnaire', 'save_training_preferences',
    'raise_long_run_cap', 'preview_capacity', 'assess_training_readiness',
    'search_tuneup_races', 'search_training_routes',
    'generate_training_route', 'build_route_workout',
    'list_training_locations', 'set_training_location_for_day',
    'match_routes_to_plan', 'infer_terrain_profile',
    # Single-GPX prediction & calibration UI tools
    'get_current_params', 'adjust_params',
    'retrain_model', 'rollback_params',
    'suggest_waypoints', 'manage_annotations',
})


def _get_cached_tools(context_type: Optional[str] = None) -> list:
    """Return AGENT_TOOLS filtered for the given context, with cache_control
    on the last tool. Cached per-context (lazy-built).

    Filtering by context cuts ~30-40% of tool-schema input tokens for the
    training-plan and race-dashboard flows — important because Anthropic's
    ITPM rate limit counts cache_read tokens too.
    """
    cache_key = context_type or 'default'
    if cache_key in _CACHED_TOOLS_BY_CONTEXT:
        return _CACHED_TOOLS_BY_CONTEXT[cache_key]

    if context_type == 'training-plan':
        excluded = _TOOLS_EXCLUDE_TRAINING_PLAN
    elif context_type == 'race-dashboard':
        excluded = _TOOLS_EXCLUDE_RACE_DASHBOARD
    else:
        excluded = frozenset()

    tools = [copy.deepcopy(t) for t in AGENT_TOOLS if t.get('name') not in excluded]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}

    _CACHED_TOOLS_BY_CONTEXT[cache_key] = tools
    return tools


def _get_client():
    """Anthropic SDK client, on AGENT_BASE_URL when set (DeepSeek and other
    Anthropic-compatible APIs), else api.anthropic.com."""
    import anthropic
    from config import agent_config
    return anthropic.Anthropic(api_key=agent_config.AGENT_API_KEY,
                               base_url=agent_config.AGENT_BASE_URL)


def _is_claude_model(model: str) -> bool:
    """True if the active model is an Anthropic Claude model."""
    return (model or '').lower().startswith('claude-')


def _strip_cache_markers(blocks: list) -> list:
    """Strip cache_control from system/tool blocks. Used when routing through
    a non-Claude provider — ephemeral caching is Anthropic-only.
    """
    out = []
    for b in blocks:
        if isinstance(b, dict):
            out.append({k: v for k, v in b.items() if k != 'cache_control'})
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# Conversation persistence (Postgres-backed)
# ---------------------------------------------------------------------------

def _load_messages(user_id: int, conversation_id: Optional[str]) -> List[Dict]:
    """Load the persisted message list for (user, conversation).

    Returns [] if the conversation doesn't exist yet. Non-fatal if the DB
    isn't available (tests without Flask context): returns an empty list.
    """
    try:
        from flask import has_app_context
        if not has_app_context():
            return []
        from repositories import AgentConversationRepository
        conv = AgentConversationRepository().get(user_id, conversation_id)
        return list(conv.messages) if conv and conv.messages else []
    except Exception:
        logger.exception('failed to load conversation; starting fresh')
        return []


def _derive_title(messages: List[Dict]) -> Optional[str]:
    """Pick a short title from the first user message (stripping any
    [Context: ...] prefix the agent prepends to round 1)."""
    for m in messages:
        if m.get('role') != 'user':
            continue
        content = m.get('content')
        if not isinstance(content, str):
            continue
        text = content.strip()
        if text.startswith('[Context:'):
            end = text.find(']')
            if end != -1:
                text = text[end + 1:].lstrip()
        text = ' '.join(text.split())
        if text:
            return text[:120]
    return None


def _save_messages(
    user_id: int,
    conversation_id: Optional[str],
    messages: List[Dict],
    context_type: Optional[str] = None,
) -> None:
    """Upsert the full message list back to the DB. Non-fatal on failure.

    We pre-flight with json.dumps so a bad block shape fails fast here
    rather than corrupting the SQLAlchemy session on flush.
    """
    try:
        from flask import has_app_context
        if not has_app_context():
            return
        try:
            json.dumps(messages)
        except (TypeError, ValueError):
            logger.warning('conversation messages not JSON-serializable; skipping persist')
            return
        from repositories import AgentConversationRepository
        repo = AgentConversationRepository()
        repo.save_messages(
            user_id,
            conversation_id,
            messages,
            context_type=context_type,
            title=_derive_title(messages),
        )
        repo.commit()
    except Exception:
        logger.exception('failed to persist conversation; history may be lost')


def _jsonable_content(content: Any) -> Any:
    """Convert Anthropic SDK content blocks to plain JSON-serializable dicts.

    Claude returns pydantic `ContentBlock` objects in `response.content`. We
    store them as dicts so the conversation survives a JSON round-trip. Falls
    back to a best-effort dict for anything that looks like a block but isn't
    a real pydantic model (useful in tests that patch with MagicMock).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [_block_to_dict(b) for b in content]
    return _block_to_dict(content)


def _block_to_dict(block: Any) -> Any:
    if isinstance(block, dict):
        return block
    if hasattr(block, 'model_dump'):
        dumped = block.model_dump()
        if isinstance(dumped, dict):
            return dumped
    # Best-effort reconstruction from the attrs we care about
    btype = getattr(block, 'type', None)
    if btype == 'text':
        return {'type': 'text', 'text': getattr(block, 'text', '')}
    if btype == 'tool_use':
        return {
            'type': 'tool_use',
            'id': getattr(block, 'id', ''),
            'name': getattr(block, 'name', ''),
            'input': getattr(block, 'input', {}),
        }
    return {'type': str(btype) if btype else 'unknown'}


# ---------------------------------------------------------------------------
# System prompt + context prefix (data-heavy, kept verbatim — intentional)
# ---------------------------------------------------------------------------

def _build_system_prompt(context_type: Optional[str] = None) -> list:
    """Build the system prompt as Anthropic content blocks with cache markers.

    Base prompt is always cached. Training-plan / race-dashboard contexts
    append a second cached block with the coaching knowledge bundle.
    """
    blocks = [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]
    if context_type in ('training-plan', 'race-dashboard'):
        knowledge = get_training_plan_knowledge()
        if knowledge:
            blocks.append({
                "type": "text",
                "text": knowledge,
                "cache_control": {"type": "ephemeral"},
            })
    return blocks


def _build_plan_edit_context(plan_id: int, user_id: int, gpx_id: Optional[int] = None) -> str:
    """Context string for when the user is editing an existing training plan."""
    from repositories import TrainingPlanRepository
    plan = TrainingPlanRepository().get_user_plan(plan_id, user_id)
    if not plan:
        return '[Context: the user is on the Training Plan page and wants to build a personalized training plan.]'

    parts = [
        f'[Context: the user is on the Training Plan page viewing their existing plan '
        f'"{plan.plan_name}" (plan_id={plan.id}, status={plan.status}).'
    ]
    if plan.race_date:
        parts.append(f' Race date: {plan.race_date}.')
    if plan.race_description:
        parts.append(f' Race: {plan.race_description}.')
    if plan.target_gpx_id:
        parts.append(f' Target GPX route ID: {plan.target_gpx_id}.')
        parts.append(_race_profile_sentence(plan.target_gpx_id, user_id))
    if plan.weeks:
        parts.append(f' Plan has {len(plan.weeks)} weeks.')
        parts.append(f' Summary: {_weekly_summary(plan.weeks)}.')

    parts.append(
        ' The user may want to modify this plan. Use adjust_training_week to modify specific weeks.'
        ' If the user asks for broad changes (e.g., "more uphills", "increase volume"), identify '
        'which weeks need changes and use adjust_training_week for each.'
        ' Do NOT ask the user to re-specify their race details — you already have the plan context.]'
    )
    return ''.join(parts)


def _race_profile_sentence(gpx_id: int, user_id: int) -> str:
    """Pre-compute race profile so the LLM doesn't redo the math."""
    try:
        from repositories import GPXFileRepository
        from services.agent.tool_handlers.validation import (
            _classify_race_profile, _compute_gpx_elevation,
        )
        gpx_file = GPXFileRepository().get_user_file(gpx_id, user_id)
        if not (gpx_file and gpx_file.data):
            return ''
        points = gpx_file.data.get('points', [])
        if not points:
            return ''
        race_dist = gpx_file.data.get('total_distance_km') or 0
        race_gain, race_loss = _compute_gpx_elevation(points)
        if race_dist <= 0 or race_gain <= 0:
            return ''
        profile = _classify_race_profile(race_gain, race_loss, race_dist)
        tr = profile['training_ratio']
        return (
            f' RACE PROFILE: {race_dist:.1f}km, '
            f'{race_gain:.0f}m D+, {race_loss:.0f}m D-. '
            f'{profile["description"]} '
            f'TRAINING TARGET RATIO: {tr:.0f}m D+/km for loops — '
            f'easy/long runs at ~{tr:.0f}m/km, '
            f'hill sessions up to ~{tr * 1.3:.0f}m/km.'
        )
    except Exception:
        return ''  # never break context building


def _weekly_summary(weeks: list) -> str:
    """Human-readable per-week km/elev/theme summary."""
    out = []
    for w in weeks:
        days = w.get('days', []) if isinstance(w, dict) else []
        total_km = sum(d.get('distance_km', 0) for d in days)
        total_elev = sum(d.get('elevation_m', 0) for d in days)
        theme = w.get('theme', '') if isinstance(w, dict) else ''
        wn = w.get('week_number', '?') if isinstance(w, dict) else '?'
        out.append(f'W{wn}: {total_km:.0f}km/{total_elev:.0f}m D+ ({theme})')
    return '; '.join(out)


def _build_context_prefix(gpx_id: Optional[int], prediction_id: Optional[int],
                          context_type: Optional[str] = None,
                          user_id: Optional[int] = None,
                          plan_id: Optional[int] = None) -> str:
    """Build the [Context: ...] block prepended to the first user message."""
    if context_type == 'race-dashboard':
        return _race_dashboard_context(user_id)

    if context_type == 'training-plan':
        if plan_id and user_id:
            return _build_plan_edit_context(plan_id, user_id, gpx_id)
        return _training_plan_intake_context(gpx_id, user_id)

    if not gpx_id:
        return ''
    parts = [f'[Context: the user is currently viewing GPX route ID {gpx_id}']
    if prediction_id:
        parts.append(f', prediction ID {prediction_id}')
    parts.append(
        '. Use this route by default — do not ask which route unless they have '
        'multiple and explicitly ask to switch.]'
    )
    return ''.join(parts)


def _race_dashboard_context(user_id: Optional[int]) -> str:
    parts = [
        '[Context: User is on Race Dashboard.',
        ' Use get_plan_compliance for detailed breakdown.',
        ' You can suggest plan adjustments using adjust_training_week.',
    ]
    from repositories import TrainingPlanRepository
    season_plans = TrainingPlanRepository().get_season_plans(user_id) if user_id else []
    if len(season_plans) >= 2:
        names = ", ".join(p.plan_name for p in season_plans)
        parts.append(f' User has {len(season_plans)} planned races: {names}.')
        parts.append(' Use get_season_overview for multi-race context.')
    parts.append(']')
    return ''.join(parts)


def _training_plan_intake_context(gpx_id: Optional[int], user_id: Optional[int]) -> str:
    """Context for the initial plan-generation intake (no plan yet)."""
    today = date.today()
    parts = [
        '[Context: the user is on the Training Plan page and wants to build a '
        'personalized training plan.',
        f' Today is {today.strftime("%Y-%m-%d")} ({today.strftime("%A")}).',
    ]

    # Example dates are computed live so the LLM doesn't reinvent arithmetic.
    example_race = date(2026, 5, 10)
    days_to_example = (example_race - today).days
    parts.append(
        '\n\nPRE-COMPUTED HELPERS (use these values, do NOT recalculate):'
        '\n- The user will state race distance, D+, and date in their message.'
        '\n- When parsing, extract: distance_km, elevation_gain_m, race_date.'
        '\n- Use this formula (already computed when you see the values):'
        '\n  weeks_to_race = (race_date - today) / 7'
        '\n  race_ratio = elevation_gain_m / distance_km (m D+/km)'
        '\n  peak_long_run_km = distance_km * 0.75 (75% of race distance)'
        '\n  peak_long_run_elev = peak_long_run_km * race_ratio'
        '\n  peak_weekly_elev = elevation_gain_m (must hit 100% of race D+ in 2 peak weeks)'
        '\n'
        '\nEXAMPLE: User says "50km 3500D+ race on 10 may"'
        f'\n  weeks_to_race = ({example_race} - {today}) = {days_to_example} days = {days_to_example // 7} weeks'
        '\n  race_ratio = 3500 / 50 = 70 m/km'
        '\n  peak_long_run = 37.5 km with 2,625m D+'
        '\n  peak_weekly_elev = 3,500m D+'
        '\n  race_date for tool = "2026-05-10", total_weeks for tool = 7'
    )

    parts.append(
        '\n\nWORKFLOW — follow these steps IN ORDER:'
        '\n1) Gather training history (get_training_history, get_training_load, assess_training_readiness)'
    )
    if gpx_id:
        parts.append(f'\n2) Analyze race GPX (get_race_profile with gpx_id={gpx_id})')
    else:
        parts.append('\n2) Do NOT call get_race_profile or list_gpx_routes (no GPX selected).')

    # Inline saved preferences so the model doesn't have to tool-call for them.
    if user_id:
        try:
            from repositories import UserTrainingPreferencesRepository
            saved = UserTrainingPreferencesRepository().get_by_user(user_id)
            if saved:
                parts.append(f'\n\nSAVED TRAINING PREFERENCES: {json.dumps(saved.to_dict())}')
        except Exception:
            pass

    parts.append(
        '\n3) Call get_training_preferences to check for saved preferences.'
        '\n   If REQUIRED fields (max_weekly_km, terrain_profile) are missing, '
        '\n   call start_onboarding_questionnaire and return its schema in the '
        '\n   response — the frontend renders the wizard automatically. '
        '\n   If the user explicitly prefers chat, walk them through each step '
        '\n   using the schema (volume → mountain → terrain → sample route), '
        '\n   then call save_training_preferences with the answers.'
        '\n   If preferences exist — confirm them briefly with the user '
        '\n   ("Vedo cap 35km/sett, terrain flat_urban, mountain 1x/sett. Confermi?").'
        '\n   Do NOT ask for confirmation after saving. Do NOT show a plan overview.'
        '\n4) Call generate_full_plan with ALL parameters from steps 1-3.'
        '\n   The handler reads saved prefs and applies user capacity caps '
        '\n   (max_weekly_km, max_long_run_km), terrain-aware midweek elevation '
        '\n   limits, and the mountain access budget automatically. '
        '\n   If the response has requires_onboarding=True, surface the wizard '
        '\n   via start_onboarding_questionnaire and stop.'
        '\n   Do NOT use generate_training_week — use generate_full_plan instead.'
        '\n   Required params: total_weeks, race_distance_km, race_elevation_m, race_date,'
        '\n   athlete_weekly_km, athlete_weekly_elev, athlete_longest_run_km, '
        '\n   athlete_category, long_run_day, rest_days.'
        '\n   MOUNTAIN DAY RULE: elevation-heavy workouts go ONLY on mountain_days '
        '\n   AND within the mountain_access_per_week budget — excess workouts are '
        '\n   downgraded automatically.'
        '\n   STRENGTH RULE: strength sessions are 0 km, 0 elev, placed on preferred days.'
        '\n5) After generate_full_plan returns, surface any warnings in the '
        '\n   response — especially severity=critical (race_terrain_mismatch). '
        '\n   For unmatched routes, propose one of suggested_alternatives '
        '\n   (generate / upload / downgrade) inline before save. Then call '
        '\n   save_training_plan and present a brief summary.]'
    )
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Core tool loop — shared by chat() and chat_stream()
# ---------------------------------------------------------------------------

def _summarize_result(result: Dict) -> str:
    """Short summary of a tool result, used for logs and SSE tool_end events."""
    if not isinstance(result, dict):
        return 'ok'
    if 'error' in result:
        return f"error: {result['error']}"
    keys = list(result.keys())
    return f"ok ({', '.join(keys[:4])}{'...' if len(keys) > 4 else ''})"


# TODO(i18n-gap #92 — see GH issues): user-facing English built server-side.
# Italian UI shows it verbatim; return a key + params and render with $t on the client.
def _tool_display_label(tool_name: str, tool_input: Dict) -> str:
    """User-facing label for the UI tool progress indicator."""
    display = TOOL_DISPLAY_NAMES.get(tool_name, f"Running {tool_name}...")
    if tool_name == 'generate_training_week':
        week_num = tool_input.get('week_number')
        if not week_num and tool_input.get('weeks'):
            nums = [w.get('week_number') for w in tool_input['weeks'] if w.get('week_number')]
            if nums:
                return f"Generating weeks {nums[0]}-{nums[-1]}..."
        elif week_num:
            return f"Generating week {week_num}..."
    return display


def _execute_tool(
    tool_name: str,
    tool_input: Dict,
    user_id: int,
    plan_gen_charged: bool,
    failure_counts: Dict[str, int],
) -> Tuple[Dict, bool]:
    """Run a single tool call, honoring plan-gen quota + repeated-failure hints.

    Returns (result, plan_gen_charged_after). The caller owns `failure_counts`
    and we mutate it in place to keep the signature simple.
    """
    allowed, sub = _check_plan_gen_quota(user_id, tool_name, plan_gen_charged)
    if not allowed:
        return _plan_gen_quota_error(sub), plan_gen_charged

    result = handle_tool_call(tool_name, tool_input, user_id)

    if (tool_name in PLAN_GEN_TOOLS
            and not plan_gen_charged
            and isinstance(result, dict)
            and 'error' not in result):
        _charge_plan_gen(user_id)
        plan_gen_charged = True

    is_error = isinstance(result, dict) and 'error' in result
    if is_error:
        failure_counts[tool_name] = failure_counts.get(tool_name, 0) + 1
        if failure_counts[tool_name] >= 2:
            result['_retry_hint'] = (
                f'This tool has failed {failure_counts[tool_name]} times in a row. '
                f'STOP retrying with the same approach. Instead, present your plan '
                f'to the user as text and explain that the plan could not be saved '
                f'automatically. The user can review your proposed plan and ask you '
                f'to try again.'
            )
    else:
        failure_counts.pop(tool_name, None)

    return result, plan_gen_charged


def _validated_weeks_from_result(tool_name: str, result: Dict) -> List[Dict]:
    """Pull streamable weeks out of a plan-gen tool result."""
    if tool_name not in ('generate_training_week', 'generate_full_plan'):
        return []
    if not isinstance(result, dict):
        return []
    weeks = result.get('weeks') or ([result] if result.get('valid') else [])
    return [w for w in weeks if isinstance(w, dict) and w.get('valid')]


def _build_done_payload(tool_calls_log: List[Dict], final_text: str) -> Dict:
    """Assemble the final response dict the frontend consumes.

    Replaces the old `_extract_suggested_annotations` / `_extract_annotations_updated`
    / `_extract_training_plan_saved` / `_extract_generated_weeks` / `_extract_plan_adjusted`
    helpers with one pass over the tool call log.
    """
    suggestions: List[Dict] = []
    annotations_updated = None
    training_plan_saved = None
    plan_adjusted = False
    generated_weeks: List[Dict] = []
    seen_weeks = set()

    for tc in tool_calls_log:
        result = tc.get('_result') or {}
        name = tc.get('tool')

        if 'suggested_annotations' in result:
            suggestions.extend(result['suggested_annotations'])

        if result.get('_annotations_updated'):
            # Most recent wins — reassigned in-order so last write sticks
            annotations_updated = result.get('annotations', [])

        if name == 'save_training_plan' and result.get('status') == 'saved':
            training_plan_saved = {
                'plan_id': result.get('plan_id'),
                'plan_name': result.get('plan_name'),
            }

        if name == 'adjust_training_week' and result.get('status') == 'updated':
            plan_adjusted = True

        for week in _validated_weeks_from_result(name, result):
            wn = week.get('week_number')
            if wn in seen_weeks:
                continue
            seen_weeks.add(wn)
            generated_weeks.append({
                'week_number': wn,
                'theme': week.get('theme'),
                'total_km': week.get('total_km'),
                'total_elevation_m': week.get('total_elevation_m'),
                'days': week.get('days', []),
            })

    clean_log = [{k: v for k, v in tc.items() if not k.startswith('_')} for tc in tool_calls_log]

    payload: Dict = {'response': final_text, 'tool_calls': clean_log, 'error': None}
    if suggestions:
        payload['suggested_annotations'] = suggestions
    if annotations_updated is not None:
        payload['annotations_updated'] = annotations_updated
    if training_plan_saved:
        payload['training_plan_saved'] = training_plan_saved
    if generated_weeks:
        payload['generated_weeks'] = generated_weeks
    if plan_adjusted:
        payload['plan_adjusted'] = True
    return payload


def _run_chat(
    user_id: int,
    user_message: str,
    conversation_id: Optional[str],
    gpx_id: Optional[int],
    prediction_id: Optional[int],
    plan_id: Optional[int],
    context_type: Optional[str],
) -> Iterator[Tuple[str, Dict]]:
    """Core generator shared by chat() and chat_stream().

    Yields progress events as (kind, data) tuples — the caller decides whether
    to turn them into SSE or to drop them. Kinds:
        'tool_start' : {tool, label}
        'tool_end'   : {tool, result_summary}
        'week'       : {week}
        'done'       : final payload dict
        'error'      : {error}

    Exactly one of 'done' or 'error' is always yielded last.
    """
    from config import agent_config
    if not agent_config.AGENT_API_KEY:
        yield 'error', {'error': 'AGENT_API_KEY not configured'}
        return

    client = _get_client()
    messages = _load_messages(user_id, conversation_id)

    # Context prefix goes on the FIRST user message of the conversation only.
    if not messages:
        prefix = _build_context_prefix(gpx_id, prediction_id, context_type, user_id, plan_id)
        if prefix:
            user_message = f'{prefix}\n\n{user_message}'

    system_prompt = _build_system_prompt(context_type)
    tools = _get_cached_tools(context_type)
    if not _is_claude_model(AGENT_MODEL):
        # Non-Claude providers ignore (or warn on) cache_control.
        system_prompt = _strip_cache_markers(system_prompt)
        tools = _strip_cache_markers(tools)
    messages.append({'role': 'user', 'content': user_message})

    tool_calls_log: List[Dict] = []
    failure_counts: Dict[str, int] = {}
    plan_gen_charged = False
    total_usage: Dict[str, int] = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read_tokens': 0,
        'cache_creation_tokens': 0,
    }

    for round_num in range(AGENT_MAX_TOOL_ROUNDS):
        try:
            response = client.messages.create(
                model=AGENT_MODEL,
                max_tokens=AGENT_MAX_TOKENS,
                system=system_prompt,
                tools=tools,
                messages=messages,
                extra_body=agent_config.AGENT_EXTRA_BODY,
            )
        except Exception as e:
            logger.exception(f'Claude API error: {e}')
            yield 'error', {'error': f'Claude API error: {e}'}
            return

        # Log cache performance for cost observability + accumulate for billing
        usage = getattr(response, 'usage', None)
        if usage is not None:
            def _as_int(v) -> int:
                try:
                    return int(v) if v is not None else 0
                except (TypeError, ValueError):
                    return 0
            cache_read = _as_int(getattr(usage, 'cache_read_input_tokens', 0))
            cache_create = _as_int(getattr(usage, 'cache_creation_input_tokens', 0))
            input_t = _as_int(getattr(usage, 'input_tokens', 0))
            output_t = _as_int(getattr(usage, 'output_tokens', 0))
            logger.info(
                f'Round {round_num + 1} tokens: '
                f'input={input_t} (cache_read={cache_read}, cache_create={cache_create}), '
                f'output={output_t}'
            )
            total_usage['input_tokens'] += input_t
            total_usage['output_tokens'] += output_t
            total_usage['cache_read_tokens'] += cache_read
            total_usage['cache_creation_tokens'] += cache_create

        # Persist the assistant turn as plain dicts (survives JSON round-trip)
        assistant_content = _jsonable_content(response.content)
        messages.append({'role': 'assistant', 'content': assistant_content})

        # Find tool_use blocks on the raw response (still typed SDK objects)
        tool_use_blocks = [b for b in response.content if b.type == 'tool_use']

        if not tool_use_blocks:
            # Model is done — collect text + emit 'done'
            text_parts = [b.text for b in response.content if b.type == 'text']
            final_text = '\n'.join(text_parts)
            _save_messages(user_id, conversation_id, messages, context_type=context_type)
            done_payload = _build_done_payload(tool_calls_log, final_text)
            done_payload['_usage'] = dict(total_usage)
            yield 'done', done_payload
            return

        # Execute tool calls + build matching tool_result blocks
        tool_results = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input
            tool_id = block.id
            tool_key = f'{tool_name}:{tool_id}'

            yield 'tool_start', {
                'tool': tool_key,
                'label': _tool_display_label(tool_name, tool_input),
            }
            logger.info(f'Agent tool call: {tool_name}({json.dumps(tool_input)[:200]})')

            result, plan_gen_charged = _execute_tool(
                tool_name, tool_input, user_id, plan_gen_charged, failure_counts,
            )

            summary = _summarize_result(result)
            tool_calls_log.append({
                'tool': tool_name,
                'input': tool_input,
                'result_summary': summary,
                '_result': result,
            })

            tool_end_payload = {'tool': tool_key, 'result_summary': summary}
            # Fast-path for plan-mutating tools: signal the frontend that the
            # calendar should be refreshed immediately, without waiting for
            # the agent to finish writing its final assistant text (which on
            # Haiku can take several extra seconds for long summaries). The
            # 'done' payload also carries training_plan_saved / plan_adjusted
            # for backwards compatibility — this is just an earlier hint.
            if isinstance(result, dict) and 'error' not in result:
                if tool_name == 'save_training_plan' and result.get('status') == 'saved':
                    tool_end_payload['plan_saved'] = {
                        'plan_id': result.get('plan_id'),
                        'plan_name': result.get('plan_name'),
                    }
                elif tool_name == 'adjust_training_week' and result.get('status') == 'updated':
                    tool_end_payload['plan_adjusted'] = True
            yield 'tool_end', tool_end_payload

            streamed_weeks = _validated_weeks_from_result(tool_name, result)
            # generate_full_plan returns all weeks in a single tool result, so
            # without pacing the frontend would render them all in one frame
            # and the per-week reveal animation would collapse. Insert a small
            # delay between yields to preserve the progressive UX. The total
            # added latency is bounded (e.g. 14 weeks * 0.15s ≈ 2.1s) and is
            # much less than the prior LLM-per-week path (~5s × N).
            pace_seconds = (
                AGENT_FULL_PLAN_WEEK_STREAM_DELAY
                if tool_name == 'generate_full_plan' and len(streamed_weeks) > 1
                else 0.0
            )
            for idx, week in enumerate(streamed_weeks):
                if pace_seconds > 0 and idx > 0:
                    time.sleep(pace_seconds)
                yield 'week', {'week': week}

            tool_results.append({
                'type': 'tool_result',
                'tool_use_id': tool_id,
                'content': json.dumps(result),
            })

        messages.append({'role': 'user', 'content': tool_results})

    # Max rounds exceeded — persist what we have and surface it
    _save_messages(user_id, conversation_id, messages, context_type=context_type)
    yield 'done', {
        'response': (
            'I reached the maximum number of steps for this request. '
            'Please try breaking your request into smaller parts.'
        ),
        'tool_calls': [{k: v for k, v in tc.items() if not k.startswith('_')}
                       for tc in tool_calls_log],
        'error': 'max_rounds_exceeded',
        '_usage': dict(total_usage),
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def chat(user_id: int, user_message: str, conversation_id: Optional[str] = None,
         gpx_id: Optional[int] = None, prediction_id: Optional[int] = None,
         plan_id: Optional[int] = None, context_type: Optional[str] = None) -> Dict:
    """Non-streaming agent call.

    Drains the internal generator and returns only the final payload dict.
    """
    for kind, data in _run_chat(user_id, user_message, conversation_id,
                                gpx_id, prediction_id, plan_id, context_type):
        if kind == 'done':
            return data
        if kind == 'error':
            return {'response': None, 'tool_calls': [], **data}
    # Should never reach here — _run_chat always yields done or error
    return {'response': None, 'tool_calls': [], 'error': 'no_response'}


def chat_stream(user_id: int, user_message: str, conversation_id: Optional[str] = None,
                gpx_id: Optional[int] = None, prediction_id: Optional[int] = None,
                plan_id: Optional[int] = None, context_type: Optional[str] = None):
    """SSE-streaming agent call.

    Maps the shared tool-loop events into `event: <kind>\\ndata: <json>\\n\\n`
    strings. Event kinds: tool_start, tool_end, week, done, error.
    """
    for kind, data in _run_chat(user_id, user_message, conversation_id,
                                gpx_id, prediction_id, plan_id, context_type):
        yield f'event: {kind}\ndata: {json.dumps(data)}\n\n'

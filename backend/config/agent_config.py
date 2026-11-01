"""Configuration for the LLM prediction agent."""

import os

# Claude API settings
AGENT_MODEL = os.environ.get('AGENT_MODEL', 'claude-haiku-4-5-20251001')
AGENT_MAX_TOKENS = 4096
AGENT_MAX_TOOL_ROUNDS = 20  # Single-week plan generation needs ~15 rounds (5 setup + 9 weeks + save)

# Server-side delay between SSE 'week' events when streaming the result of
# generate_full_plan, so the frontend calendar reveal animates progressively.
# Set to 0 to disable pacing (all weeks emitted as fast as possible).
AGENT_FULL_PLAN_WEEK_STREAM_DELAY = float(
    os.environ.get('AGENT_FULL_PLAN_WEEK_STREAM_DELAY', '0.15')
)

# API key from environment
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# Conversation cache TTL (seconds)
CONVERSATION_CACHE_TTL = 1800  # 30 minutes

# Per-tier usage limits. Keeps AI COGS bounded vs subscription revenue.
# Chat msg ~ $0.015, plan-gen ~ $0.25 on Haiku 4.5 with prompt cache.
# Daily token caps are billed on (input + output*5) where input counts
# cache-creation full + cache-read at 1/10 weight (matches Anthropic pricing).
# Targets: free ~$0.05/mo, race_day_pass ~$1/week, premium ~$3/mo on Haiku.
TIER_LIMITS = {
    'free':            {'chat_per_day': 3,  'plan_gens_per_period': 0, 'daily_input_tokens': 30_000,  'daily_output_tokens': 4_000},
    'premium_monthly': {'chat_per_day': 15, 'plan_gens_per_period': 5, 'daily_input_tokens': 400_000, 'daily_output_tokens': 60_000},
    'premium_yearly':  {'chat_per_day': 15, 'plan_gens_per_period': 5, 'daily_input_tokens': 400_000, 'daily_output_tokens': 60_000},
    'race_day_pass':   {'chat_per_day': 8,  'plan_gens_per_period': 2, 'daily_input_tokens': 150_000, 'daily_output_tokens': 25_000},
    # Assigned by hand in the DB (not purchasable: billing.VALID_CHECKOUT_PLANS).
    # Caps stay finite so a runaway tool loop can't burn the LLM budget.
    'developer':       {'chat_per_day': 500, 'plan_gens_per_period': 200, 'daily_input_tokens': 10_000_000, 'daily_output_tokens': 1_000_000},
}

# Any Anthropic-compatible endpoint (OpenRouter: https://openrouter.ai/api).
# Unset = api.anthropic.com. AGENT_API_KEY falls back to ANTHROPIC_API_KEY.
AGENT_BASE_URL = (os.environ.get('AGENT_BASE_URL', '') or '').strip() or None
AGENT_API_KEY = (os.environ.get('AGENT_API_KEY', '') or '').strip() or ANTHROPIC_API_KEY
# OpenRouter rotates hosts and each switch starts with a cold prompt cache.
# AGENT_PROVIDERS=DeepInfra,Novita pins the hosts (in order) so cache reads hit:
# measured 2026-10-24, the second call cost about a fifth of the first.
_providers = [p.strip() for p in os.environ.get('AGENT_PROVIDERS', '').split(',') if p.strip()]
AGENT_EXTRA_BODY = ({'provider': {'order': _providers, 'allow_fallbacks': False,
                                  'require_parameters': True}}
                    if _providers else None)

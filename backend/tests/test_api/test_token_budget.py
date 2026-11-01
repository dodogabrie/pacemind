"""Tests for the per-user daily Anthropic token budget."""

from datetime import date, timedelta

import pytest

from app import create_app
from database import db
from models import UserSubscription


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


def _make_sub(plan: str = 'free') -> UserSubscription:
    return UserSubscription(user_id=1, plan=plan, status='active')


def test_free_caps_match_tier_limits(app):
    with app.app_context():
        sub = _make_sub('free')
        assert sub.daily_input_token_cap == 30_000
        assert sub.daily_output_token_cap == 4_000


def test_premium_caps_match_tier_limits(app):
    with app.app_context():
        sub = _make_sub('premium_monthly')
        assert sub.daily_input_token_cap == 400_000
        assert sub.daily_output_token_cap == 60_000


def test_can_spend_returns_true_on_fresh_day(app):
    with app.app_context():
        sub = _make_sub('free')
        assert sub.can_spend_tokens(estimated_input=2000, estimated_output=200) is True


def test_record_usage_weights_cache_read_at_one_tenth(app):
    """cache_read tokens count at 1/10 weight; cache_creation counts full."""
    with app.app_context():
        sub = _make_sub('free')
        sub.record_token_usage(
            input_tokens=10_000,
            output_tokens=500,
            cache_read_tokens=10_000,    # adds 1_000 weighted
            cache_creation_tokens=5_000,  # adds 5_000 full
        )
        assert sub.agent_input_tokens_today == 10_000 + 5_000 + 1_000
        assert sub.agent_output_tokens_today == 500


def test_can_spend_blocks_when_cap_reached(app):
    with app.app_context():
        sub = _make_sub('free')
        sub.record_token_usage(input_tokens=29_000, cache_read_tokens=10_000)
        # weighted_input = 29_000 + 1_000 = 30_000 -> cap hit exactly
        assert sub.can_spend_tokens(estimated_input=1) is False


def test_output_cap_blocks_independently(app):
    with app.app_context():
        sub = _make_sub('free')
        sub.record_token_usage(output_tokens=4_000)
        # input still has headroom but output is at cap
        assert sub.can_spend_tokens(estimated_input=1, estimated_output=1) is False


def test_daily_rollover_resets_counters(app):
    with app.app_context():
        sub = _make_sub('free')
        sub.record_token_usage(input_tokens=29_000)
        sub.agent_tokens_reset_date = date.today() - timedelta(days=1)
        # Next call should see a fresh day -> can spend again, and recording
        # zeroes the counter before adding.
        assert sub.can_spend_tokens(estimated_input=2_000) is True
        sub.record_token_usage(input_tokens=2_000)
        assert sub.agent_input_tokens_today == 2_000
        assert sub.agent_tokens_reset_date == date.today()


def test_tokens_remaining_dict_shape(app):
    with app.app_context():
        sub = _make_sub('premium_monthly')
        sub.record_token_usage(input_tokens=100_000, output_tokens=10_000)
        remaining = sub.tokens_remaining_today()
        assert remaining == {
            'input_remaining': 300_000,
            'output_remaining': 50_000,
            'input_cap': 400_000,
            'output_cap': 60_000,
        }

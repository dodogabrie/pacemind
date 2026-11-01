"""User subscription model for monetization.

Tracks subscription status, plan type, and Stripe integration.
"""

from database import db
from datetime import datetime, timezone

from config.agent_config import TIER_LIMITS


class UserSubscription(db.Model):
    """Tracks user subscription status and billing."""
    __tablename__ = 'user_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)

    # Plan info
    plan = db.Column(db.String(32), nullable=False, default='free')
    # 'free', 'premium_monthly', 'premium_yearly', 'race_day_pass'

    # Stripe references
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)

    # Status
    status = db.Column(db.String(32), nullable=False, default='active')
    # 'active', 'canceled', 'past_due', 'expired'

    # Timestamps
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)
    canceled_at = db.Column(db.DateTime, nullable=True)

    # Usage tracking
    agent_messages_today = db.Column(db.Integer, default=0)
    agent_messages_reset_date = db.Column(db.Date, nullable=True)
    plan_generations_this_period = db.Column(db.Integer, default=0)
    plan_generations_reset_date = db.Column(db.Date, nullable=True)

    # Daily Anthropic token spend (caps Anthropic COGS per user-day).
    # cache-read tokens count at 1/10 weight, cache-creation at full weight.
    agent_input_tokens_today = db.Column(db.Integer, default=0)
    agent_output_tokens_today = db.Column(db.Integer, default=0)
    agent_tokens_reset_date = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship
    user = db.relationship('User', backref=db.backref('subscription', uselist=False))

    # ---------- helpers ----------

    @property
    def is_premium(self) -> bool:
        """Check if user has an active premium subscription."""
        if self.plan == 'free':
            return False
        if self.status != 'active':
            return False
        if self.expires_at:
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return False
        return True

    @property
    def _limits(self) -> dict:
        """Active tier limits. Falls back to free if unknown plan."""
        if self.is_premium:
            return TIER_LIMITS.get(self.plan, TIER_LIMITS['free'])
        return TIER_LIMITS['free']

    @property
    def chat_daily_limit(self) -> int:
        return self._limits['chat_per_day']

    @property
    def plan_generation_period_limit(self) -> int:
        return self._limits['plan_gens_per_period']

    @property
    def daily_input_token_cap(self) -> int:
        return self._limits.get('daily_input_tokens', 30_000)

    @property
    def daily_output_token_cap(self) -> int:
        return self._limits.get('daily_output_tokens', 4_000)

    # ---------- chat messages (daily) ----------

    @property
    def can_use_agent(self) -> bool:
        """Check if user can send another agent chat message today."""
        today = datetime.now(timezone.utc).date()
        if self.agent_messages_reset_date != today:
            return True  # Fresh day; counter rolls on next increment
        return (self.agent_messages_today or 0) < self.chat_daily_limit

    def increment_agent_usage(self):
        """Track an agent message. Resets daily."""
        today = datetime.now(timezone.utc).date()
        if self.agent_messages_reset_date != today:
            self.agent_messages_today = 1
            self.agent_messages_reset_date = today
        else:
            self.agent_messages_today = (self.agent_messages_today or 0) + 1

    @property
    def agent_messages_remaining(self) -> int:
        """Chat messages remaining today."""
        limit = self.chat_daily_limit
        today = datetime.now(timezone.utc).date()
        if self.agent_messages_reset_date != today:
            return limit
        return max(0, limit - (self.agent_messages_today or 0))

    # ---------- Anthropic token budget (daily) ----------

    def _refresh_token_window(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self.agent_tokens_reset_date != today:
            self.agent_input_tokens_today = 0
            self.agent_output_tokens_today = 0
            self.agent_tokens_reset_date = today

    def _today_token_counts(self) -> tuple:
        """(input_used, output_used) for today, or (0, 0) on a fresh day."""
        today = datetime.now(timezone.utc).date()
        if self.agent_tokens_reset_date != today:
            return 0, 0
        return (self.agent_input_tokens_today or 0, self.agent_output_tokens_today or 0)

    def can_spend_tokens(self, estimated_input: int = 2000, estimated_output: int = 200) -> bool:
        """Pre-flight check: would another agent call exceed today's token cap?"""
        used_in, used_out = self._today_token_counts()
        if used_in + estimated_input > self.daily_input_token_cap:
            return False
        if used_out + estimated_output > self.daily_output_token_cap:
            return False
        return True

    def record_token_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Accumulate token spend for today.

        `input_tokens` from the SDK is the *fresh* input on that turn.
        `cache_creation_tokens` counts at full weight (priced like input).
        `cache_read_tokens` counts at 1/10 weight per Anthropic pricing.
        """
        self._refresh_token_window()
        weighted_input = (input_tokens or 0) + (cache_creation_tokens or 0) + (cache_read_tokens or 0) // 10
        self.agent_input_tokens_today = (self.agent_input_tokens_today or 0) + weighted_input
        self.agent_output_tokens_today = (self.agent_output_tokens_today or 0) + (output_tokens or 0)

    def tokens_remaining_today(self) -> dict:
        used_in, used_out = self._today_token_counts()
        return {
            'input_remaining': max(0, self.daily_input_token_cap - used_in),
            'output_remaining': max(0, self.daily_output_token_cap - used_out),
            'input_cap': self.daily_input_token_cap,
            'output_cap': self.daily_output_token_cap,
        }

    # ---------- plan generations (per billing period) ----------

    def _plan_gen_period_start(self) -> 'date':
        """Start of current plan-gen quota period.

        Premium: first of the current calendar month.
        Race Day Pass: subscription start date (pass lasts 7 days).
        """
        today = datetime.now(timezone.utc).date()
        if self.plan == 'race_day_pass' and self.started_at:
            return self.started_at.date()
        return today.replace(day=1)

    def _refresh_plan_gen_window(self) -> None:
        """Roll the plan-gen counter to zero if a new period started."""
        window_start = self._plan_gen_period_start()
        if self.plan_generations_reset_date != window_start:
            self.plan_generations_this_period = 0
            self.plan_generations_reset_date = window_start

    @property
    def can_generate_plan(self) -> bool:
        """Check if user can start another plan generation in the current period."""
        limit = self.plan_generation_period_limit
        if limit <= 0:
            return False
        window_start = self._plan_gen_period_start()
        if self.plan_generations_reset_date != window_start:
            return True  # New period; counter rolls on next increment
        return (self.plan_generations_this_period or 0) < limit

    def increment_plan_generation(self):
        """Track a plan generation. Rolls over per period."""
        self._refresh_plan_gen_window()
        self.plan_generations_this_period = (self.plan_generations_this_period or 0) + 1

    @property
    def plan_generations_remaining(self) -> int:
        """Plan generations remaining in the current period."""
        limit = self.plan_generation_period_limit
        if limit <= 0:
            return 0
        window_start = self._plan_gen_period_start()
        if self.plan_generations_reset_date != window_start:
            return limit
        return max(0, limit - (self.plan_generations_this_period or 0))

    # ---------- serialization ----------

    def to_dict(self) -> dict:
        """Convert to API response dict."""
        return {
            'plan': self.plan,
            'status': self.status,
            'is_premium': self.is_premium,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'agent_messages_remaining': self.agent_messages_remaining,
            'chat_daily_limit': self.chat_daily_limit,
            'plan_generations_remaining': self.plan_generations_remaining,
            'plan_generation_period_limit': self.plan_generation_period_limit,
            'tokens_remaining_today': self.tokens_remaining_today(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
        }

    @classmethod
    def get_or_create(cls, user_id: int) -> 'UserSubscription':
        """Get existing subscription or create free tier."""
        sub = cls.query.filter_by(user_id=user_id).first()
        if not sub:
            sub = cls(user_id=user_id, plan='free', status='active')
            db.session.add(sub)
            db.session.commit()
        return sub

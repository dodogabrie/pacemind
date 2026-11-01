"""User subscription repository."""

from typing import Optional
from models import UserSubscription
from repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[UserSubscription]):
    model = UserSubscription

    def get_for_user(self, user_id: int) -> Optional[UserSubscription]:
        return self.find_one_by(user_id=user_id)

    def get_or_create(self, user_id: int) -> UserSubscription:
        """Get existing subscription or create free tier."""
        sub = self.get_for_user(user_id)
        if not sub:
            sub = UserSubscription(user_id=user_id, plan='free', status='active')
            self.create(sub)
        return sub

    def get_by_stripe_subscription(self, stripe_subscription_id: str) -> Optional[UserSubscription]:
        return self.find_one_by(stripe_subscription_id=stripe_subscription_id)

    def update_plan(self, sub: UserSubscription, plan: str, **kwargs) -> None:
        """Update subscription plan and related fields."""
        sub.plan = plan
        for key, value in kwargs.items():
            if hasattr(sub, key):
                setattr(sub, key, value)

    def increment_agent_usage(self, sub: UserSubscription) -> None:
        """Increment agent message counter."""
        sub.increment_agent_usage()

    def record_token_usage(
        self,
        sub: UserSubscription,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Add Anthropic token spend to today's daily counter."""
        sub.record_token_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

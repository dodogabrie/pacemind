"""Repository for agent chat history."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from models import AgentConversation
from repositories.base import BaseRepository


class AgentConversationRepository(BaseRepository[AgentConversation]):
    model = AgentConversation

    def get(self, user_id: int, conversation_id: Optional[str]) -> Optional[AgentConversation]:
        return self.find_one_by(
            user_id=user_id,
            conversation_id=conversation_id or 'default',
        )

    def get_or_create(
        self,
        user_id: int,
        conversation_id: Optional[str],
        context_type: Optional[str] = None,
    ) -> AgentConversation:
        conv = self.get(user_id, conversation_id)
        if conv is not None:
            # Backfill context on legacy rows the first time we see them.
            if context_type and not conv.context_type:
                conv.context_type = context_type
            return conv
        conv = AgentConversation(
            user_id=user_id,
            conversation_id=conversation_id or 'default',
            messages=[],
            context_type=context_type,
        )
        return self.create(conv)

    def save_messages(
        self,
        user_id: int,
        conversation_id: Optional[str],
        messages: List[dict],
        context_type: Optional[str] = None,
        title: Optional[str] = None,
    ) -> AgentConversation:
        """Upsert the full message list for this conversation."""
        conv = self.get_or_create(user_id, conversation_id, context_type=context_type)
        conv.messages = messages
        conv.last_active_at = datetime.now(timezone.utc)
        if context_type and not conv.context_type:
            conv.context_type = context_type
        if title and not conv.title:
            conv.title = title[:120]
        self.flush()
        return conv

    def list_for_user(
        self,
        user_id: int,
        context_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[AgentConversation]:
        """Most-recent-first list of a user's conversations."""
        q = self.model.query.filter_by(user_id=user_id)
        if context_type:
            q = q.filter(self.model.context_type == context_type)
        return (
            q.order_by(self.model.last_active_at.desc())
             .limit(limit)
             .all()
        )

    def delete_one(self, user_id: int, conversation_id: str) -> bool:
        conv = self.get(user_id, conversation_id)
        if conv is None:
            return False
        self.delete(conv)
        return True

    def delete_for_user(self, user_id: int) -> int:
        """Remove all chat history for a user (GDPR / account-delete flow)."""
        count = self.model.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        self.flush()
        return count

    def cleanup_older_than(self, days: int = 30) -> int:
        """Delete conversations whose last activity is older than `days` days.

        Intended to be called from a maintenance script. Returns the number of
        rows removed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = self.model.query.filter(
            self.model.last_active_at < cutoff
        ).delete(synchronize_session=False)
        self.flush()
        return count

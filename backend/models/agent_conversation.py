"""Persistent agent chat history.

One row per (user_id, conversation_id) pair. Replaces the in-memory cache
that used to live in agent_service, so conversations survive server restarts
and users can resume where they left off.
"""

from datetime import datetime, timezone

from database import db


class AgentConversation(db.Model):
    __tablename__ = 'agent_conversations'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'conversation_id', name='uq_agent_conv_user_conv'),
        db.Index('ix_agent_conv_user_last_active', 'user_id', 'last_active_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Client-chosen id (or 'default' when the frontend omits it). Kept as a
    # short string so the same user can run multiple independent conversations.
    conversation_id = db.Column(db.String(64), nullable=False, default='default')

    # Full message list in Claude API shape: [{role, content}, ...]. Each
    # assistant-turn content is serialized to plain dicts (not Anthropic SDK
    # objects) so the value is always JSON-round-trippable.
    messages = db.Column(db.JSON, nullable=False, default=list)

    # Surface used to start the conversation (e.g. 'training-plan',
    # 'race-dashboard'). Lets the UI list a user's history scoped per surface.
    context_type = db.Column(db.String(32), nullable=True, index=True)

    # Short human-friendly label, derived from the first user message. Shown
    # in the history list. Re-derived only if still null.
    title = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime,
                           default=lambda: datetime.now(timezone.utc),
                           nullable=False)
    last_active_at = db.Column(db.DateTime,
                               default=lambda: datetime.now(timezone.utc),
                               onupdate=lambda: datetime.now(timezone.utc),
                               nullable=False)

    user = db.relationship('User', backref=db.backref('agent_conversations', lazy='dynamic'))

    def __repr__(self):
        n = len(self.messages or [])
        return f'<AgentConversation u={self.user_id} c={self.conversation_id} msgs={n}>'

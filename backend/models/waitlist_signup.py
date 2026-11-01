"""Waitlist signup model for public plan waitlists (e.g. Coach & Team)."""

from database import db
from datetime import datetime, timezone


class WaitlistSignup(db.Model):
    __tablename__ = 'waitlist_signups'
    __table_args__ = (
        db.UniqueConstraint('email', 'plan', name='uq_waitlist_email_plan'),
        db.Index('ix_waitlist_plan_created', 'plan', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    plan = db.Column(db.String(32), nullable=False)
    source = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    ip_hash = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email': self.email,
            'plan': self.plan,
            'source': self.source,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

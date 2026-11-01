"""Waitlist signup repository."""

from typing import Optional, Tuple
from sqlalchemy.exc import IntegrityError

from database import db
from models import WaitlistSignup
from repositories.base import BaseRepository


class WaitlistRepository(BaseRepository[WaitlistSignup]):
    model = WaitlistSignup

    def create_signup(
        self,
        email: str,
        plan: str,
        source: Optional[str] = None,
        ip_hash: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[WaitlistSignup, bool]:
        """Create a signup; if (email, plan) already exists, return existing.

        Returns (signup, created) — created=False when duplicate.
        """
        existing = WaitlistSignup.query.filter_by(email=email, plan=plan).first()
        if existing is not None:
            return existing, False

        signup = WaitlistSignup(
            email=email,
            plan=plan,
            source=source,
            ip_hash=ip_hash,
            user_agent=user_agent,
        )
        try:
            db.session.add(signup)
            db.session.flush()
            return signup, True
        except IntegrityError:
            db.session.rollback()
            existing = WaitlistSignup.query.filter_by(email=email, plan=plan).first()
            return existing, False

    def count_by_plan(self, plan: str) -> int:
        return WaitlistSignup.query.filter_by(plan=plan).count()

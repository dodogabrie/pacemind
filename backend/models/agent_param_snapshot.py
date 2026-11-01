"""Agent parameter snapshot model for rollback support."""

from datetime import datetime, timezone
from database import db


class AgentParamSnapshot(db.Model):
    """Stores parameter snapshots before agent modifications.

    Enables rollback of agent-initiated parameter changes.
    Keeps last N snapshots per user for undo history.
    """

    __tablename__ = 'agent_param_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Snapshot of all physics parameters at the time of change
    params_snapshot = db.Column(db.JSON, nullable=False)

    # What triggered the snapshot
    action = db.Column(db.String(64), nullable=False)  # 'adjust_params', 'retrain_model'
    description = db.Column(db.String(256))  # Human-readable description of change

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = db.relationship('User', backref=db.backref('param_snapshots', lazy='dynamic'))

    MAX_SNAPSHOTS_PER_USER = 20

    def __repr__(self):
        return f'<AgentParamSnapshot user_id={self.user_id} action={self.action} at={self.created_at}>'

    @classmethod
    def create_snapshot(cls, user_id: int, params: dict, action: str, description: str = None):
        """Create a snapshot and prune old ones.

        Args:
            user_id: User ID
            params: Current parameter dict to snapshot
            action: What triggered the snapshot
            description: Human-readable description

        Returns:
            Created snapshot
        """
        snapshot = cls(
            user_id=user_id,
            params_snapshot=params,
            action=action,
            description=description
        )
        db.session.add(snapshot)

        # Prune old snapshots (keep last N)
        old_snapshots = (
            cls.query
            .filter_by(user_id=user_id)
            .order_by(cls.created_at.desc())
            .offset(cls.MAX_SNAPSHOTS_PER_USER)
            .all()
        )
        for old in old_snapshots:
            db.session.delete(old)

        return snapshot

    @classmethod
    def get_latest(cls, user_id: int):
        """Get most recent snapshot for user.

        Args:
            user_id: User ID

        Returns:
            Latest snapshot or None
        """
        return (
            cls.query
            .filter_by(user_id=user_id)
            .order_by(cls.created_at.desc())
            .first()
        )

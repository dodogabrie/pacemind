"""Agent param snapshot repository."""

from typing import Optional, List
from models import AgentParamSnapshot
from repositories.base import BaseRepository


class AgentSnapshotRepository(BaseRepository[AgentParamSnapshot]):
    model = AgentParamSnapshot

    def get_latest(self, user_id: int) -> Optional[AgentParamSnapshot]:
        """Get most recent snapshot for user."""
        return AgentParamSnapshot.query.filter_by(user_id=user_id) \
            .order_by(AgentParamSnapshot.created_at.desc()).first()

    def get_user_snapshots(self, user_id: int, limit: int = 20) -> List[AgentParamSnapshot]:
        """Get snapshots for user, limited to most recent."""
        return AgentParamSnapshot.query.filter_by(user_id=user_id) \
            .order_by(AgentParamSnapshot.created_at.desc()) \
            .limit(limit).all()

    def create_snapshot(self, user_id: int, params: dict,
                         action: str, description: str) -> AgentParamSnapshot:
        """Create new snapshot, auto-pruning old ones."""
        return AgentParamSnapshot.create_snapshot(
            user_id=user_id,
            params=params,
            action=action,
            description=description
        )

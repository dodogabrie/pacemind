"""Linking of external provider accounts (Strava, later Garmin/…) to a User.

Owns the account-identity rules that used to live in
`UserRepository.find_or_create_from_strava`: which user an incoming OAuth
callback belongs to, and when linking must be refused.
"""

from typing import Optional

from models import User, UserConnection
from repositories import UserConnectionRepository, UserRepository


class ConnectionConflictError(Exception):
    """Raised when a provider account is already linked to a different user."""
    pass


class ConnectionService:

    def __init__(self):
        self.connection_repo = UserConnectionRepository()
        self.user_repo = UserRepository()

    def find_user(self, provider: str, external_user_id) -> Optional[User]:
        """Find the user owning a provider account, or None."""
        connection = self.connection_repo.get_by_external_id(provider, external_user_id)
        if connection:
            return self.user_repo.get_by_id(connection.user_id)
        # Fallback for rows the backfill has not reached (or a partially
        # migrated DB): the legacy column on `users` is still authoritative.
        if provider == 'strava':
            try:
                return self.user_repo.get_by_strava_id(int(external_user_id))
            except (TypeError, ValueError):
                return None
        return None

    def link(self, user: User, provider: str, external_user_id,
             token_data: dict = None, scopes: str = None) -> UserConnection:
        """Attach a provider account to `user`, or refresh an existing link.

        Raises ConnectionConflictError if the provider account belongs to a
        different user, or if `user` already has a *different* account linked
        for this provider.
        """
        external_user_id = str(external_user_id)

        owner = self.find_user(provider, external_user_id)
        if owner is not None and owner.id != user.id:
            raise ConnectionConflictError(
                f"{provider} account {external_user_id} is already linked to another PaceMind account"
            )

        connection = self.connection_repo.get_for_user(user.id, provider)
        if connection is None:
            connection = UserConnection(user_id=user.id, provider=provider,
                                        external_user_id=external_user_id)
            self.connection_repo.create(connection)
        elif connection.external_user_id != external_user_id:
            raise ConnectionConflictError(
                f"this account is already connected to a different {provider} account"
            )

        connection.status = 'active'
        if scopes:
            connection.scopes = scopes
        if token_data:
            connection.access_token = token_data.get('access_token')
            connection.refresh_token = token_data.get('refresh_token')
            connection.expires_at = token_data.get('expires_at')
        return connection

    def link_strava(self, user: User, athlete: dict, token_data: dict = None,
                    scopes: str = None) -> UserConnection:
        """Link a Strava athlete and keep the legacy `users` columns in sync.

        # ponytail: dual-write. ~9 read sites (strava_service, sync, agent
        # tools) still read user.strava_user_id / user.access_token. Phase 1
        # moves those readers onto UserConnection and this drops to link().
        """
        connection = self.link(user, 'strava', athlete.get('id'), token_data, scopes)
        user.strava_user_id = athlete.get('id')
        if athlete.get('username'):
            user.strava_username = athlete.get('username')
        if token_data:
            self.user_repo.update_tokens(user, token_data)
        return connection

    def find_or_create_from_strava(self, athlete: dict, token_data: dict = None,
                                   scopes: str = None) -> User:
        """Log-in path for a not-logged-in Strava callback: find or create."""
        user = self.find_user('strava', athlete.get('id'))
        if user is None:
            user = User(
                strava_user_id=athlete.get('id'),
                strava_username=athlete.get('username'),
                email=athlete.get('email'),
                auth_provider='strava',
            )
            self.user_repo.create(user)
        self.link_strava(user, athlete, token_data, scopes)
        return user

    def disconnect(self, user: User, provider: str) -> bool:
        """Mark a connection revoked and clear its tokens. Keeps the account."""
        connection = self.connection_repo.get_for_user(user.id, provider)
        if connection is None:
            return False
        connection.status = 'revoked'
        connection.access_token = None
        connection.refresh_token = None
        connection.expires_at = None
        if provider == 'strava':
            user.access_token = None
            user.refresh_token = None
            user.expires_at = None
        return True


"""Shared utilities for API endpoints."""

from flask import request
from api.auth import verify_jwt, get_jwt_from_request
from repositories import UserRepository

user_repo = UserRepository()


def get_current_user():
    """Get current user from JWT token (header or httpOnly cookie).

    Returns:
        User object if authenticated, None otherwise
    """
    token = get_jwt_from_request()
    if not token:
        return None

    user_id = verify_jwt(token)
    if not user_id:
        return None

    return user_repo.get_by_id(user_id)

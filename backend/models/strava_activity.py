"""Deprecation shim — `StravaActivity` is now `Activity`.

Kept so the ~10 services and tests that import `StravaActivity` keep working
through the rename. Delete once the last import is gone.
"""

from models.activity import Activity as StravaActivity  # noqa: F401

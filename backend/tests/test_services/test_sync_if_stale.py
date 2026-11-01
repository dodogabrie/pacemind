from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.strava_sync_service import StravaSyncService


def _svc(started_at, status='completed', refresh='tok'):
    st = MagicMock(started_at=started_at, status=status)
    svc = StravaSyncService(user_repo=MagicMock(), activity_repo=MagicMock(),
                            sync_status_repo=MagicMock(), residual_repo=MagicMock())
    svc.user_repo.get_by_id.return_value = MagicMock(refresh_token=refresh)
    svc.sync_status_repo.get_or_create.return_value = st
    svc.sync_user_async = MagicMock()
    return svc


def test_stale_triggers_incremental_sync():
    svc = _svc(datetime.now(timezone.utc) - timedelta(hours=7))
    assert svc.sync_if_stale(1) is True
    svc.sync_user_async.assert_called_once_with(1)


def test_never_synced_triggers():
    assert _svc(None).sync_if_stale(1) is True


def test_fresh_running_or_unconnected_skip():
    now = datetime.now(timezone.utc)
    assert _svc(now - timedelta(hours=1)).sync_if_stale(1) is False
    assert _svc(now - timedelta(hours=9), status='syncing').sync_if_stale(1) is False
    assert _svc(None, refresh=None).sync_if_stale(1) is False


def test_push_event_mid_sync_marks_resync():
    svc = _svc(datetime.now(timezone.utc), status='syncing')
    svc.sync_status_repo.get_or_create.return_value.resync_pending = False
    assert svc.sync_if_stale(1, max_age_hours=0) is False
    assert svc.sync_status_repo.get_or_create.return_value.resync_pending is True

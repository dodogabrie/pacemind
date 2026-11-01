"""Background import of a user's activity files (Garmin/Strava/Polar exports).

Same shape as `StravaSyncService`: a daemon thread, its own app context, and
progress on the `sync_status` row — this one keyed `provider='upload'`, so a
Strava sync and a file import can run side by side.

The processing rules that matter (docs/plans/multi-source-activities/03-file-ingest.md):

* **Stream, don't load.** One file in memory at a time, and the upload is
  deleted from disk as soon as the job ends. A Garmin export is ~800 files.
* **Sport filter.** Only running / trail running / hiking feed the model.
* **Partial failure is normal.** A corrupt FIT is one skipped line in the
  report, never an aborted import.
* **Idempotent.** Re-dropping the same archive changes nothing: the content
  hash is the external_id and the dedup key catches the rest.
* **Downstream work runs once**, at the end — calibration and tier training are
  expensive and pointless per file.
"""

import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone

from config.hybrid_config import TIER_2_MIN_ACTIVITIES
from repositories import ActivityRepository, SyncStatusRepository
from services.activity_ingest import NORMALIZERS, ActivityIngestService
from services.activity_ingest.archive import (
    ArchiveRejected, count_activity_files, file_kind, iter_activity_files)
from services.activity_ingest.normalizers import (
    UnusableActivity, is_supported_sport)

logger = logging.getLogger(__name__)

PROVIDER = 'upload'

# Commit every N activities: one commit per file is slow, one commit at the end
# loses everything on a crash and shows no progress.
COMMIT_EVERY = 25

# Only the first N skipped files are reported back — a user who drops a folder
# of cycling FITs would otherwise get a 5000-line error blob.
MAX_REPORTED_SKIPS = 50


class ActivityImportService:
    """Parses an uploaded archive into activities, in the background."""

    def __init__(self, activity_repo=None, sync_status_repo=None,
                 ingest_service=None):
        self.activity_repo = activity_repo or ActivityRepository()
        self.sync_status_repo = sync_status_repo or SyncStatusRepository()
        self.ingest_service = ingest_service or ActivityIngestService()

    # ── entry points ─────────────────────────────────────────────────────────

    def start_async(self, user_id: int, upload_path: str, job_dir: str):
        """Kick off the import and return immediately."""
        thread = threading.Thread(target=self._run_in_app_context,
                                  args=(user_id, upload_path, job_dir))
        thread.daemon = True
        thread.start()
        logger.info(f"Started activity import for user {user_id}: {upload_path}")
        return thread

    def _run_in_app_context(self, user_id, upload_path, job_dir):
        try:
            from app import create_app
            with create_app().app_context():
                # Fresh repos: the ones on `self` belong to the request thread.
                service = ActivityImportService()
                service.run(user_id, upload_path, job_dir)
        except Exception as e:
            logger.error(f"Activity import crashed for user {user_id}: {e}",
                         exc_info=True)

    def run(self, user_id: int, upload_path: str, job_dir: str) -> dict:
        """Do the import synchronously. Returns the summary it also stored."""
        status = self.sync_status_repo.get_or_create(user_id, PROVIDER)
        status.status = 'syncing'
        status.current_step = 'parsing_files'
        status.started_at = datetime.now(timezone.utc)
        status.completed_at = None
        status.error_message = None
        status.downloaded_activities = 0
        status.message = 'Reading your export...'
        try:
            status.total_activities = count_activity_files(upload_path)
        except Exception:
            status.total_activities = 0
        self.sync_status_repo.commit()

        try:
            imported, skipped, cancelled = self._process(user_id, upload_path, status)
        except ArchiveRejected as e:
            self._finish_error(status, str(e))
            return {'imported': 0, 'skipped': 0, 'skipped_files': [],
                    'error': str(e)}
        except Exception as e:
            logger.error(f"Import failed for user {user_id}: {e}", exc_info=True)
            self._finish_error(status, 'Import failed while reading the archive')
            return {'imported': 0, 'skipped': 0, 'skipped_files': [],
                    'error': str(e)}
        finally:
            _cleanup(job_dir)

        # The result rides in error_message — it is the only free Text column
        # on sync_status. `GET /api/activities/import` splits it back out as
        # `result` so a completed import never surfaces as an error to the UI.
        result = {'imported': imported, 'skipped': len(skipped),
                  'skipped_files': skipped[:MAX_REPORTED_SKIPS]}
        status.error_message = json.dumps(result)

        if cancelled:
            status.status = 'cancelled'
            status.current_step = None
            status.message = f'Import cancelled after {imported} activities.'
            status.completed_at = datetime.now(timezone.utc)
            self.sync_status_repo.commit()
            return {**result, 'cancelled': True}

        if imported:
            self._run_downstream_once(user_id, status)

        summary = f'{imported} imported'
        if skipped:
            summary += f', {len(skipped)} skipped'
        status.status = 'completed'
        status.current_step = None
        status.message = summary
        status.completed_at = datetime.now(timezone.utc)
        self.sync_status_repo.commit()
        logger.info(f"Import finished for user {user_id}: {summary}")
        return result

    # ── internals ────────────────────────────────────────────────────────────

    def _process(self, user_id, upload_path, status):
        imported, seen, skipped = 0, 0, []

        for name, data, error in iter_activity_files(upload_path):
            if self._is_cancelled(user_id):
                return imported, skipped, True
            seen += 1
            if error:
                skipped.append({'name': name, 'reason': error})
            else:
                reason = self._ingest_one(user_id, name, data)
                if reason:
                    skipped.append({'name': name, 'reason': reason})
                else:
                    # TODO(multi-source #21 — see GH issues): also counts files already present.
                    # ingest() doesn't say created vs updated, so a re-import reports "N imported".
                    # Fix: ingest() returns the outcome and we count already_present apart.
                    imported += 1
            del data  # the whole point: one file's bytes live at a time

            if seen % COMMIT_EVERY == 0:
                status.downloaded_activities = imported
                status.message = f'Imported {imported} activities...'
                self.sync_status_repo.commit()

        status.downloaded_activities = imported
        self.sync_status_repo.commit()
        return imported, skipped, False

    def _ingest_one(self, user_id, name, data) -> str:
        """Ingest one file. Returns '' on success or a skip reason."""
        normalizer = NORMALIZERS.get(file_kind(name))
        if normalizer is None:
            return 'unsupported file type'
        try:
            normalized = normalizer(data, name)
        except UnusableActivity as e:
            return str(e)
        except Exception as e:
            # Untrusted input through a third-party parser: any exception is
            # expected traffic, not a crash.
            logger.info(f"Could not parse {name}: {e}")
            return f'unreadable file ({type(e).__name__})'

        if not is_supported_sport(normalized.sport_type):
            return f'not a running activity ({normalized.sport_type})'

        try:
            self.ingest_service.ingest(user_id, normalized)
        except Exception as e:
            logger.error(f"Could not store {name}: {e}", exc_info=True)
            self.activity_repo.rollback()
            return 'could not be stored'
        return ''

    # TODO(multi-source #17 — see GH issues): a process death mid-import leaves
    # this row saying 'syncing' forever, and POST /api/activities/import then
    # 409s for good. sync_status.updated_at is a live heartbeat (we commit
    # every COMMIT_EVERY files) — sweep stale 'syncing' rows on app start, or
    # move both this and StravaSyncService onto a real queue with a lease.
    def _is_cancelled(self, user_id) -> bool:
        status = self.sync_status_repo.get_for_user(user_id, PROVIDER)
        return status is not None and status.status == 'cancelled'

    def _run_downstream_once(self, user_id, status):
        """Calibration + tier training + plan compliance, once for the batch."""
        from services.strava_sync_service import StravaSyncService

        total = self.activity_repo.count_for_user(user_id)
        sync = StravaSyncService()
        try:
            # Reusing the sync service's training verbatim: the rules must not
            # fork between "synced from Strava" and "imported from a file".
            if total >= TIER_2_MIN_ACTIVITIES:
                status.current_step = 'training_tier2'
                status.message = 'Learning your running parameters...'
                self.sync_status_repo.commit()
                sync._train_tier2_params(user_id, [])
        except Exception as e:
            logger.error(f"Post-import training failed for user {user_id}: {e}",
                         exc_info=True)

        try:
            from services.plan_compliance_service import PlanComplianceService
            PlanComplianceService().check_compliance(user_id)
        except Exception as e:
            logger.error(f"Post-import compliance failed for user {user_id}: {e}")

    def _finish_error(self, status, message):
        status.status = 'error'
        status.current_step = None
        status.error_message = message
        status.message = message
        status.completed_at = datetime.now(timezone.utc)
        self.sync_status_repo.commit()


def _cleanup(job_dir):
    if job_dir and os.path.isdir(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)

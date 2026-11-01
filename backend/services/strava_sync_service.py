"""Strava sync service - downloads activities and trains model on login.

Handles the initial sync when user connects Strava account.
"""
import logging
import threading
from datetime import datetime, timezone

from flask import current_app

from config.hybrid_config import TIER_2_MIN_ACTIVITIES
from models import Activity
from models.sync_status import SyncStatus
from models.user import User
from repositories import (
    ActivityRepository,
    SyncStatusRepository,
    UserActivityResidualRepository,
    UserRepository,
)
from services.activity_ingest import ActivityIngestService
from services.activity_ingest.normalizers.strava import normalize_strava
from services.parameter_learning_service import ParameterLearningService
from services.strava_service import StravaService
from services.user_residual_service import UserResidualService

logger = logging.getLogger(__name__)


class StravaSyncService:
    """Handles background sync of Strava activities and model training."""

    # Max number of most-relevant activities to download streams for per sync.
    MAX_STREAMS_PER_SYNC = 50

    def __init__(self, user_repo=None, activity_repo=None, sync_status_repo=None, residual_repo=None):
        self.user_repo = user_repo or UserRepository()
        self.activity_repo = activity_repo or ActivityRepository()
        self.sync_status_repo = sync_status_repo or SyncStatusRepository()
        self.residual_repo = residual_repo or UserActivityResidualRepository()

    def sync_if_stale(self, user_id: int, max_age_hours: int = 6) -> bool:
        """Start an incremental sync if the last attempt is older than max_age_hours.

        Called when an active user opens the app (auth status), so data never
        goes stale without a manual click. Keyed on started_at (set on every
        attempt, even failed) so errors don't retry on every page load.
        Strava push events (api/strava.py webhook) call this with max_age_hours=0.
        """
        user = self.user_repo.get_by_id(user_id)
        if not user or not user.refresh_token:
            return False
        st = self.sync_status_repo.get_or_create(user_id)
        if st.status == 'syncing':
            if max_age_hours == 0 and not st.resync_pending:
                st.resync_pending = True
                self.sync_status_repo.commit()
            return False
        last = st.started_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last).total_seconds() < max_age_hours * 3600:
                return False
        st.status = 'syncing'
        st.started_at = datetime.now(timezone.utc)
        st.message = 'Starting Strava sync...'
        self.sync_status_repo.commit()
        self.sync_user_async(user_id)
        return True

    def sync_user_async(self, user_id: int, full: bool = False):
        """Start background sync for user after Strava connection.

        Args:
            user_id: ID of user who just connected Strava
            full: re-read the whole last year instead of only runs newer than
                the latest stored one (the "reload activities" button)
        """
        thread = threading.Thread(
            target=self._sync_until_settled,
            args=(user_id, full)
        )
        thread.daemon = True
        thread.start()
        logger.info(f"Started background Strava sync for user {user_id}")

    def _sync_until_settled(self, user_id: int, full: bool = False):
        """Run the sync, then again (incremental) while push events arrived mid-run."""
        from app import create_app
        app = create_app()
        for _ in range(3):  # ponytail: cap so a stuck flag can't loop forever
            self._sync_user_background(user_id, full)
            full = False
            with app.app_context():
                repo = SyncStatusRepository()
                st = repo.get_for_user(user_id)
                if not st or not st.resync_pending:
                    return
                st.resync_pending = False
                repo.commit()

    def _sync_user_background(self, user_id: int, full: bool = False):
        """Background worker to download activities and train model.

        Fetches all running activities, scores by distance + elevation,
        downloads streams for top 15, and trains Tier 2/3 model.

        Args:
            user_id: User ID
        """
        try:
            from app import create_app
            app = create_app()

            with app.app_context():
                # Create fresh repos inside app context for background thread
                user_repo = UserRepository()
                activity_repo = ActivityRepository()
                sync_status_repo = SyncStatusRepository()
                residual_repo = UserActivityResidualRepository()

                user = user_repo.get_by_id(user_id)
                if not user or not user.access_token:
                    logger.error(f"User {user_id} not found or no access token")
                    return

                # Initialize or get sync status
                sync_status = sync_status_repo.get_or_create(user_id)

                sync_status.status = 'syncing'
                sync_status.started_at = datetime.now(timezone.utc)
                sync_status.current_step = 'fetching_activities'
                sync_status.message = 'Fetching and scoring your activities from Strava...'
                sync_status_repo.commit()

                logger.info(f"Starting Strava sync for user {user_id}")

                # Step 1: Download all recent activities
                activities = self._download_all_activities(user, sync_status, activity_repo=activity_repo, sync_status_repo=sync_status_repo, residual_repo=residual_repo, full=full)
                logger.info(f"Downloaded {len(activities)} activities for user {user_id}")

                total_available = activity_repo.count_for_user(user_id)

                if len(activities) == 0:
                    sync_status.status = 'completed'
                    sync_status.current_step = None
                    if total_available == 0:
                        sync_status.message = 'Found 0 activities. Need 5+ for personalization.'
                        logger.info(f"User {user_id} has no activities, skipping training")
                    else:
                        sync_status.message = 'No new activities found. Your model is up to date.'
                        logger.info(f"User {user_id} has no new activities, skipping training")
                    sync_status.completed_at = datetime.now(timezone.utc)
                    sync_status_repo.commit()
                    return

                # Step 2: Use downloaded activities for training (already filtered by score)
                selected_activities = activities
                logger.info(f"Using {len(selected_activities)} new activities for training refresh")

                # Step 3: Train model based on tier
                if total_available >= TIER_2_MIN_ACTIVITIES:
                    sync_status.current_step = 'training_tier2'
                    sync_status.message = 'Learning your running parameters (Tier 2)...'
                    sync_status_repo.commit()
                    self._train_tier2_params(user_id, selected_activities)

                # Step 4: Check plan compliance
                try:
                    from services.plan_compliance_service import PlanComplianceService
                    compliance_service = PlanComplianceService()
                    compliance_service.check_compliance(user_id)
                    logger.info(f"Plan compliance check completed for user {user_id}")
                except Exception as e:
                    logger.error(f"Error checking plan compliance for user {user_id}: {e}")

                # Step 4b: Apply readiness-driven plan adjustments. Falls back to
                # PassiveReadinessService (TSB) when no DailyCheckin is logged
                # — see coach-review #55.
                try:
                    from services.plan_adjustment_service import PlanAdjustmentService
                    PlanAdjustmentService().apply_for_user(user_id)
                    logger.info(f"Plan adjustment applied for user {user_id}")
                except Exception as e:
                    logger.error(f"Error applying plan adjustment for user {user_id}: {e}")

                # Step 4c: fill the route library from recurring routes (best-effort)
                try:
                    from services.route_suggestion_service import sync_frequent_routes
                    sync_frequent_routes(user_id)
                except Exception as e:
                    logger.error(f"Error syncing frequent routes for user {user_id}: {e}")

                # Step 4c: fill the route library from recurring routes (best-effort)
                try:
                    from services.route_suggestion_service import sync_frequent_routes
                    sync_frequent_routes(user_id)
                except Exception as e:
                    logger.error(f"Error syncing frequent routes for user {user_id}: {e}")

                # Mark as completed
                sync_status.status = 'completed'
                sync_status.current_step = None
                sync_status.message = f'Model trained with {total_available} activities!'
                sync_status.completed_at = datetime.now(timezone.utc)
                sync_status_repo.commit()

                logger.info(f"Strava sync completed for user {user_id}")

        except Exception as e:
            logger.error(f"Error in Strava sync for user {user_id}: {e!s}", exc_info=True)
            # Try to record the error on the existing sync_status row.
            # We may or may not still hold an app context here (the failure
            # could have happened before or after the `with` block), so guard
            # both branches.
            try:
                from flask import has_app_context

                def _record_error():
                    err_sync_repo = SyncStatusRepository()
                    sync_status = err_sync_repo.get_for_user(user_id)
                    if sync_status:
                        sync_status.status = 'error'
                        sync_status.error_message = str(e)
                        err_sync_repo.commit()

                if has_app_context():
                    _record_error()
                else:
                    from app import create_app
                    with create_app().app_context():
                        _record_error()
            except Exception as record_err:
                logger.error(
                    f"Failed to record sync error for user {user_id}: {record_err}",
                    exc_info=True,
                )

    def _download_all_activities(self, user: User, sync_status: SyncStatus,
                                 activity_repo=None, sync_status_repo=None, residual_repo=None,
                                 full: bool = False) -> list[Activity]:
        """Download user's most relevant activities from Strava.

        Fetches all running activities, scores them by distance + elevation,
        and downloads streams for the top ``MAX_STREAMS_PER_SYNC`` most relevant.

        Args:
            user: User object with Strava credentials

        Returns:
            List of top Activity objects (capped at MAX_STREAMS_PER_SYNC)
        """
        # Use passed repos or create defaults
        activity_repo = activity_repo or ActivityRepository()
        sync_status_repo = sync_status_repo or SyncStatusRepository()
        residual_repo = residual_repo or UserActivityResidualRepository()

        try:
            # Initialize Strava service
            strava_service = StravaService(
                current_app.config['STRAVA_CLIENT_ID'],
                current_app.config['STRAVA_CLIENT_SECRET'],
                current_app.config['STRAVA_REDIRECT_URI']
            )

            # Ensure token is valid
            access_token, refresh_token, expires_at = strava_service.get_valid_token(
                user.access_token,
                user.refresh_token,
                user.expires_at
            )

            # Update tokens if refreshed
            if access_token != user.access_token:
                user.access_token = access_token
                user.refresh_token = refresh_token
                user.expires_at = expires_at
                activity_repo.commit()

            # Get activities since the last stored one (or last year if none)
            user_activities = activity_repo.get_user_activities(user.id, limit=1)
            latest_activity = user_activities[0] if user_activities else None
            if latest_activity and not full:
                after_timestamp = int(latest_activity.start_date.timestamp()) + 1
            else:
                after_timestamp = strava_service.get_timestamp_for_last_year()
            activities_data = strava_service.fetch_activities(access_token, after_timestamp)

            # Filter for runs only
            run_activities = [a for a in activities_data if a.get('type') == 'Run']

            logger.info(f"Found {len(run_activities)} running activities")

            # Score activities by distance (+ elevation if available)
            for activity in run_activities:
                distance_km = activity.get('distance', 0) / 1000
                elevation_m = activity.get('total_elevation_gain', 0)
                # Mixed score: distance + elevation (normalized)
                activity['_score'] = distance_km + (elevation_m / 100 if elevation_m else 0)

            # TODO(pred-review #97 — see GH issues): top-N by distance/elevation,
            # all-time; the Tier 2 fit wants the most recent runs. Keep streams
            # for the last ~20 runs plus the top-N, then re-run the backtest.
            # Sort by score descending and select top N (slice handles short lists)
            run_activities.sort(key=lambda a: a.get('_score', 0), reverse=True)
            selected_activities = run_activities[:self.MAX_STREAMS_PER_SYNC]

            logger.info(f"Selected top {len(selected_activities)} activities by distance/elevation")

            # Update total count
            sync_status.total_activities = len(selected_activities)
            sync_status.current_step = 'downloading_streams'
            sync_status.message = f'Downloading {len(selected_activities)} most relevant activities...'
            sync_status_repo.commit()

            downloaded_activities = []
            new_downloads = 0

            # Initialize residual service for collecting training data
            residual_service = UserResidualService()
            ingest_service = ActivityIngestService(
                activity_repo=activity_repo, residual_repo=residual_repo,
                residual_service=residual_service)

            for i, activity_data in enumerate(selected_activities):
                # Update progress
                if i % 5 == 0:  # Update every 5 activities
                    sync_status.downloaded_activities = i
                    sync_status.message = f'Downloaded {i}/{len(selected_activities)} activities...'
                    sync_status_repo.commit()
                # Check if already exists
                existing = activity_repo.get_by_strava_id(user.id, activity_data['id'])

                if existing:
                    logger.debug(f"Activity {activity_data['id']} already exists")

                    # Check if residuals exist, collect if missing
                    residual_exists = residual_repo.get_by_activity(
                        user.id, str(activity_data['id'])
                    )

                    if not residual_exists and existing.streams:
                        try:
                            logger.info(f"Collecting missing residuals for existing activity {activity_data['id']}")
                            residual = residual_service.collect_residuals_from_activity(
                                user_id=user.id,
                                activity_id=str(activity_data['id']),
                                activity_streams=existing.streams,
                                activity_metadata={
                                    'start_date': existing.start_date,
                                    'distance': existing.distance,
                                    'elevation': activity_data.get('total_elevation_gain', 0)
                                }
                            )
                            if residual:
                                logger.info(f"Collected residuals for existing activity {activity_data['id']}")
                        except Exception as e:
                            logger.error(f"Error collecting residuals for existing activity: {e}")

                    # Summary refresh (no streams): backfills the race flag and
                    # start coordinates of rows stored before they were ingested.
                    ingest_service.ingest(user.id, normalize_strava(activity_data),
                                          collect_residuals=False)
                    downloaded_activities.append(existing)
                    continue

                # Download streams
                logger.info(f"Downloading streams for activity {activity_data['id']}: {activity_data.get('name')}")
                streams = strava_service.download_streams(activity_data['id'], access_token)
                new_downloads += 1

                # Create activity record + collect residuals, via the single
                # activity write path.
                activity = ingest_service.ingest(
                    user.id, normalize_strava(activity_data, streams))

                downloaded_activities.append(activity)
                logger.info(f"Saved activity {activity_data['id']}")

            # Every other run as a summary row (no streams): training load,
            # weekly volume and the agent's history need the whole log, not
            # just the top-N picked to train the model.
            for activity_data in run_activities[self.MAX_STREAMS_PER_SYNC:]:
                ingest_service.ingest(user.id, normalize_strava(activity_data),
                                      collect_residuals=False)

            # Final update
            sync_status.downloaded_activities = len(downloaded_activities)
            activity_repo.commit()

            logger.info(f"Sync complete: {len(downloaded_activities)} total activities ({new_downloads} newly downloaded)")
            return downloaded_activities

        except Exception as e:
            logger.error(f"Error downloading activities: {e!s}", exc_info=True)
            return []

    def _train_tier2_params(self, user_id: int, activities: list[Activity]):
        """Train Tier 2 learned parameters.

        Args:
            user_id: User ID
            activities: List of activities to use for training
        """
        try:
            logger.info(f"Training Tier 2 parameters for user {user_id} with {len(activities)} activities")
            parameter_service = ParameterLearningService()

            # Train using all available activities (service will filter appropriately)
            learned_params = parameter_service.train_user_params(user_id)

            if learned_params:
                logger.info(f"Tier 2 training successful for user {user_id}")
            else:
                logger.warning(f"Tier 2 training failed for user {user_id}")

        except Exception as e:
            logger.error(f"Error training Tier 2 for user {user_id}: {e!s}", exc_info=True)

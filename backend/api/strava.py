import hmac

from cryptography.fernet import InvalidToken
from flask import Blueprint, current_app, jsonify, request

from api.utils import get_current_user
from repositories import ActivityRepository, SyncStatusRepository, UserRepository
from services.strava_service import StravaNotConnected, StravaService
from services.strava_sync_service import StravaSyncService

bp = Blueprint('strava', __name__, url_prefix='/api/strava')

user_repo = UserRepository()
activity_repo = ActivityRepository()
sync_status_repo = SyncStatusRepository()

def get_strava_service():
    """Get configured Strava service instance."""
    return StravaService(
        current_app.config['STRAVA_CLIENT_ID'],
        current_app.config['STRAVA_CLIENT_SECRET'],
        current_app.config['STRAVA_REDIRECT_URI']
    )

@bp.route('/activities', methods=['GET'])
def get_activities():
    """Fetch user activities from Strava."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        service = get_strava_service()

        # Ensure token is valid
        access_token, refresh_token, expires_at = service.get_valid_token(
            user.access_token,
            user.refresh_token,
            user.expires_at
        )

        # Update user tokens if refreshed
        if access_token != user.access_token:
            user.access_token = access_token
            user.refresh_token = refresh_token
            user.expires_at = expires_at
            user_repo.commit()

        # Get query parameters
        after = request.args.get('after', type=int)
        force_refresh = request.args.get('force_refresh', 'false').lower() == 'true'

        if not after:
            after = service.get_timestamp_for_last_year()

        # Try to use cached activities first
        from services.cache_service import CacheService
        cache_service = CacheService()

        activities = None
        if not force_refresh:
            activities = cache_service.get_cached_activities(user.id, max_age_hours=24)

        # Fetch from Strava if no cache or force refresh
        if activities is None:
            activities = service.fetch_activities(access_token, after)
            # Cache the fetched activities
            cache_service.cache_activities(user.id, activities, after)

        # Check which activities have streams downloaded
        activity_ids = [a['id'] for a in activities]
        downloaded_activities = activity_repo.get_downloaded_ids(user.id, activity_ids)

        downloaded_ids = {a.strava_id: (a.streams is not None) for a in downloaded_activities}

        # Add has_streams field to each activity
        for activity in activities:
            activity['has_streams'] = downloaded_ids.get(activity['id'], False)
            activity['strava_id'] = activity['id']  # Normalize field name

        return jsonify({
            'activities': activities,
            'total': len(activities)
        })

    except StravaNotConnected:
        return jsonify({'activities': [], 'total': 0, 'strava_connected': False})
    except InvalidToken:
        return jsonify({'error': 'Strava tokens are invalid (cannot decrypt). Please reconnect Strava.'}), 401
    except Exception as e:
        current_app.logger.error(f"Fetch activities error: {e!s}")
        return jsonify({'error': 'Failed to fetch activities'}), 500


@bp.route('/sync', methods=['POST'])
def start_sync():
    """Reload the last year of Strava runs (the "reload activities" button)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    if not user.refresh_token:
        return jsonify({'error': 'Strava not connected'}), 400

    sync_status = sync_status_repo.get_or_create(user.id)
    if sync_status.status == 'syncing':
        return jsonify({'error': 'A sync is already running'}), 409
    # Marked here, not only in the worker thread, so a double click can't start two.
    sync_status.status = 'syncing'
    sync_status.message = 'Starting Strava sync...'
    sync_status_repo.commit()

    StravaSyncService().sync_user_async(user.id, full=True)
    return jsonify({'status': 'syncing'}), 202


@bp.route('/sync-status', methods=['GET'])
def get_sync_status():
    """Get background Strava sync status for the current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    sync_status = sync_status_repo.get_for_user(user.id)
    if not sync_status:
        return jsonify({
            'status': 'idle',
            'current_step': None,
            'total_activities': 0,
            'downloaded_activities': 0,
            'progress_percent': 0,
            'message': 'Awaiting Strava sync to start...',
            'error_message': None,
            'started_at': None,
            'completed_at': None
        })

    return jsonify(sync_status.to_dict())


def _webhook_key_ok(key):
    token = current_app.config.get('STRAVA_WEBHOOK_VERIFY_TOKEN')
    return bool(token) and hmac.compare_digest(key, token)


@bp.route('/webhook/<key>', methods=['GET'])
def webhook_verify(key):
    """Strava push subscription handshake (one-time, at subscription create)."""
    if not _webhook_key_ok(key) or request.args.get('hub.verify_token') != key:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'hub.challenge': request.args.get('hub.challenge')})


@bp.route('/webhook/<key>', methods=['POST'])
def webhook_event(key):
    """Strava push event: new/edited activity -> incremental sync; deauth -> drop tokens.

    Strava wants a 200 within 2 s, so the sync runs in the background thread.
    Strava does not sign events, so the callback URL carries the secret
    (STRAVA_WEBHOOK_VERIFY_TOKEN): only Strava knows it.
    """
    if not _webhook_key_ok(key):
        return jsonify({'error': 'Not found'}), 404
    event = request.get_json(silent=True) or {}
    user = user_repo.get_by_strava_id(event.get('owner_id'))
    if not user:
        return '', 200
    if event.get('object_type') == 'athlete' and (event.get('updates') or {}).get('authorized') == 'false':
        user.access_token = None
        user.refresh_token = None
        user_repo.commit()
    elif event.get('object_type') == 'activity' and event.get('aspect_type') in ('create', 'update'):
        try:
            StravaSyncService().sync_if_stale(user.id, max_age_hours=0)
        except Exception:
            current_app.logger.exception('webhook sync failed')
    return '', 200

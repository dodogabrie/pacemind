"""Activity import endpoints — bring a season of history in one drop.

Deliberately NOT part of `api/gpx.py`: that uploads a *route* file to predict
on. An activity is a different object with a different lifecycle, and sharing
the endpoint would conflate the two in both the API and the UI.

    POST   /api/activities/import   multipart, one archive or N loose files
    GET    /api/activities/import   poll progress + the skipped-file report
           /api/activities/import/status   (alias, what the UI polls)
    DELETE /api/activities/import   cancel an in-flight import
"""

import json
import logging
import os
import tempfile
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from api.utils import get_current_user
from repositories import SyncStatusRepository
from services.activity_import_service import PROVIDER, ActivityImportService
from services.activity_ingest.archive import (
    MAX_UPLOAD_BYTES, is_activity_file)

logger = logging.getLogger(__name__)

bp = Blueprint('activities', __name__, url_prefix='/api/activities')

sync_status_repo = SyncStatusRepository()

ACCEPTED_SUFFIXES = ('.zip', '.gz', '.fit', '.tcx', '.gpx')


@bp.route('/import', methods=['POST'])
def start_import():
    """Accept an export archive (or loose activity files) and import it async."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    # 'files' is what the dropzone sends; 'file' keeps curl and the docs honest.
    files = [f for f in (request.files.getlist('files')
                         + request.files.getlist('file')) if f and f.filename]
    if not files:
        return jsonify({'error': 'No file provided'}), 400
    if not all(f.filename.lower().endswith(ACCEPTED_SUFFIXES) for f in files):
        return jsonify({
            'error': 'Upload a vendor export (.zip) or .fit/.tcx/.gpx files'
        }), 400

    existing = sync_status_repo.get_for_user(user.id, PROVIDER)
    if existing and existing.status == 'syncing':
        return jsonify({'error': 'An import is already running',
                        'status': existing.to_dict()}), 409

    length = request.content_length or 0
    if length > MAX_UPLOAD_BYTES:
        return jsonify({
            'error': f'Upload is too large (limit '
                     f'{MAX_UPLOAD_BYTES // (1024 * 1024)} MB). Split the '
                     f'export and drop it in parts.'
        }), 413

    # Per-job temp dir: nothing from one user's upload can collide with, or be
    # read by, another's, and the whole directory is removed when the job ends.
    job_dir = tempfile.mkdtemp(prefix=f'import_{user.id}_{uuid.uuid4().hex[:8]}_')
    upload_path = _save_upload(files, job_dir)
    if upload_path is None:
        return jsonify({'error': 'No activity files in the upload'}), 400

    ActivityImportService().start_async(user.id, upload_path, job_dir)
    return jsonify({'status': 'started', 'provider': PROVIDER}), 202


@bp.route('/import', methods=['GET'])
@bp.route('/import/status', methods=['GET'])
def import_status():
    """Progress of the current/last import, plus the skipped-file report."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    status = sync_status_repo.get_for_user(user.id, PROVIDER)
    if not status:
        return jsonify({'status': 'idle', 'provider': PROVIDER,
                        'progress_percent': 0, 'result': None})

    payload = status.to_dict()
    payload['result'] = None
    # A finished import stores its summary in error_message (the only free Text
    # column on sync_status). Split it back out so "3 files skipped" never
    # renders as "the import failed".
    if status.status != 'error' and status.error_message:
        try:
            payload['result'] = json.loads(status.error_message)
            payload['error_message'] = None
        except ValueError:
            pass
    return jsonify(payload)


@bp.route('/import', methods=['DELETE'])
def cancel_import():
    """Ask the running import to stop; it checks between files."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    status = sync_status_repo.get_for_user(user.id, PROVIDER)
    if not status or status.status != 'syncing':
        return jsonify({'error': 'No import is running'}), 404
    status.status = 'cancelled'
    status.message = 'Cancelling...'
    sync_status_repo.commit()
    return jsonify({'status': 'cancelled'})


def _save_upload(files, job_dir):
    """Write the upload into the job dir. Returns the path to process.

    Several loose files are re-packed into one zip so the import job has a
    single code path — the zip reader already caps and validates everything.
    """
    import zipfile

    if len(files) == 1:
        name = secure_filename(files[0].filename) or 'upload.zip'
        path = os.path.join(job_dir, name)
        files[0].save(path)
        return path

    path = os.path.join(job_dir, 'upload.zip')
    written = 0
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as zf:
        for index, f in enumerate(files):
            name = secure_filename(f.filename)
            if not name or not is_activity_file(name):
                continue
            member = os.path.join(job_dir, f'{index}_{name}')
            f.save(member)
            zf.write(member, arcname=name)
            os.remove(member)
            written += 1
    if not written:
        return None
    return path


# ── Races (pred-review #96/#101) ─────────────────────────────────────────────
#     GET  /api/activities/races          marked races + detected candidates
#     POST /api/activities/<id>/race      {"is_race": bool} -> race_source='user'

@bp.route('/races', methods=['GET'])
def list_races():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    from services.race_detection_service import race_overview
    return jsonify(race_overview(user.id))


@bp.route('/<int:activity_id>/race', methods=['POST'])
def mark_race(activity_id):
    """The user's call on one activity: a race or not. Retrains in the background."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    is_race = (request.get_json(silent=True) or {}).get('is_race')
    if not isinstance(is_race, bool):
        return jsonify({'error': 'is_race must be true or false'}), 400
    from repositories import ActivityRepository
    from services.parameter_learning_service import train_async
    repo = ActivityRepository()
    activity = repo.find_one_by(id=activity_id, user_id=user.id)
    if not activity:
        return jsonify({'error': 'Activity not found'}), 404
    activity.is_race, activity.race_source = is_race, 'user'
    repo.commit()
    # Only runs with streams feed the race ratio and the personal model.
    if activity.streams is not None:
        train_async(user.id)
    return jsonify({'id': activity.id, 'is_race': activity.is_race, 'race_source': activity.race_source})


@bp.route('/<int:activity_id>/analysis', methods=['GET'])
def activity_analysis(activity_id):
    """Post-workout page: same data as the MCP tools, plus a chart profile."""
    from services.agent.tool_handlers.activities import (
        _ensure_streams, _get_activity, _handle_compare_to_plan,
        _handle_get_activity_detail, analysis_profile)
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    act = _get_activity(activity_id, user.id)
    if not act:
        return jsonify({'error': 'Activity not found'}), 404
    detail = _handle_get_activity_detail({'activity_id': activity_id}, user.id)
    streams = _ensure_streams(act, user.id)
    return jsonify({
        'detail': detail,
        'plan': _handle_compare_to_plan({'activity_id': activity_id}, user.id),
        'profile': analysis_profile(streams) if streams else [],
        'sport_type': act.sport_type,
    })


@bp.route('/<int:activity_id>/improvement', methods=['GET'])
def activity_improvement(activity_id):
    """Improvement index on a stretch; query args mirror the MCP tool."""
    from services.agent.tool_handlers.activities import _handle_get_segment_improvement
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    args = {k: request.args.get(k) for k in
            ('start_km', 'end_km', 'metric', 'tolerance_m', 'period_days')}
    out = _handle_get_segment_improvement({'activity_id': activity_id, **args}, user.id)
    if out.get('error') == 'Activity not found':
        return jsonify(out), 404
    return jsonify(out)

import os
import uuid

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from models import GPXFile
from api.utils import get_current_user
from services.gpx_parser import parse_gpx_file
from services.data_processor import process_gpx_data
from repositories import GPXFileRepository

bp = Blueprint('gpx', __name__, url_prefix='/api/gpx')

gpx_repo = GPXFileRepository()

@bp.route('/upload', methods=['POST'])
def upload_gpx():
    """Upload and parse GPX file."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.endswith('.gpx'):
        return jsonify({'error': 'File must be a GPX file'}), 400

    # The app-wide MAX_CONTENT_LENGTH is sized for activity-export archives
    # (api/activities.py); a route file has no business being that big.
    max_bytes = current_app.config.get('MAX_GPX_UPLOAD_BYTES', 16 * 1024 * 1024)
    if (request.content_length or 0) > max_bytes:
        return jsonify({'error': 'GPX file is too large'}), 413

    try:
        # Save file
        original_filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{original_filename}"
        upload_folder = current_app.config['UPLOAD_FOLDER']

        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)

        # Parse GPX
        parsed_data = parse_gpx_file(file_path)
        processed_data = process_gpx_data(parsed_data)

        # Create database record
        gpx_file = GPXFile(
            user_id=user.id,
            filename=unique_filename,
            original_filename=original_filename,
            file_path=file_path,
            data=processed_data
        )

        gpx_repo.create(gpx_file)
        gpx_repo.commit()

        return jsonify({
            'id': gpx_file.id,
            'filename': gpx_file.original_filename,
            'upload_date': gpx_file.upload_date.isoformat(),
            'total_distance': processed_data['total_distance']
        }), 201

    except Exception as e:
        current_app.logger.error(f"GPX upload error: {str(e)}")
        return jsonify({'error': 'Failed to process GPX file'}), 500

@bp.route('/list', methods=['GET'])
def list_gpx_files():
    """List all GPX files for current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    gpx_files = gpx_repo.get_user_files(user.id)

    return jsonify({
        'files': [f.to_dict() for f in gpx_files]
    })

@bp.route('/<int:gpx_id>', methods=['GET'])
def get_gpx_file(gpx_id):
    """Get GPX file metadata."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)

    if not gpx_file:
        return jsonify({'error': 'GPX file not found'}), 404

    return jsonify(gpx_file.to_dict())

@bp.route('/<int:gpx_id>/data', methods=['GET'])
def get_gpx_data(gpx_id):
    """Get parsed GPX data."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)

    if not gpx_file:
        return jsonify({'error': 'GPX file not found'}), 404

    if not gpx_file.data:
        return jsonify({'error': 'No data available'}), 404

    return jsonify(gpx_file.data)

@bp.route('/<int:gpx_id>', methods=['DELETE'])
def delete_gpx_file(gpx_id):
    """Delete GPX file."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    gpx_file = gpx_repo.get_user_file(gpx_id, user.id)

    if not gpx_file:
        return jsonify({'error': 'GPX file not found'}), 404

    try:
        # Delete physical file
        if os.path.exists(gpx_file.file_path):
            os.remove(gpx_file.file_path)

        # Delete database record
        gpx_repo.delete(gpx_file)
        gpx_repo.commit()

        return jsonify({'message': 'GPX file deleted successfully'})

    except Exception as e:
        current_app.logger.error(f"GPX deletion error: {str(e)}")
        return jsonify({'error': 'Failed to delete GPX file'}), 500

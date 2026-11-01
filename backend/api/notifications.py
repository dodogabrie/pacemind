"""Notification API endpoints."""

from flask import Blueprint, jsonify
from api.utils import get_current_user
from services.notification_service import NotificationService

bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

notification_service = NotificationService()


@bp.route('/', methods=['GET'])
def list_notifications():
    """Get recent notifications for the current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    notifications = notification_service.get_notifications(user.id)
    unread_count = notification_service.get_unread_count(user.id)

    return jsonify({
        'notifications': notifications,
        'unread_count': unread_count,
    })


@bp.route('/<int:notification_id>/read', methods=['PUT'])
def mark_read(notification_id):
    """Mark a single notification as read."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    success = notification_service.mark_read(notification_id, user.id)
    if not success:
        return jsonify({'error': 'Notification not found'}), 404

    return jsonify({'status': 'read'})


@bp.route('/read-all', methods=['PUT'])
def mark_all_read():
    """Mark all notifications as read."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    count = notification_service.mark_all_read(user.id)
    return jsonify({'status': 'ok', 'updated': count})

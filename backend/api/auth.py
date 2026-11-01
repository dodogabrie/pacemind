import requests

from flask import Blueprint, request, jsonify, redirect, make_response, current_app, url_for
from models import User
from services.connection_service import ConnectionConflictError, ConnectionService
from services.mailer import send_email
from services.strava_service import StravaService
from services.strava_sync_service import StravaSyncService
from repositories import UserRepository
import jwt
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

bp = Blueprint('auth', __name__, url_prefix='/api/auth')

user_repo = UserRepository()

# Magic links are short-lived; they arrive by email and are clicked immediately.
MAGIC_LINK_TTL_MINUTES = 15

def get_strava_service():
    """Get configured Strava service instance."""
    return StravaService(
        current_app.config['STRAVA_CLIENT_ID'],
        current_app.config['STRAVA_CLIENT_SECRET'],
        current_app.config['STRAVA_REDIRECT_URI']
    )

def generate_jwt(user_id):
    """Generate JWT token for user."""
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=current_app.config['JWT_EXPIRATION_HOURS'])
    }
    return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

def verify_jwt(token):
    """Verify JWT token and return user_id."""
    try:
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_jwt_from_request():
    """Extract JWT token from Authorization header or httpOnly cookie.

    Returns:
        JWT token string, or None if not found.
    """
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        return auth_header.split(' ')[1]
    return request.cookies.get('jwt_token')

@bp.route('/strava', methods=['GET'])
def get_strava_auth_url():
    """Get Strava authorization URL."""
    service = get_strava_service()
    auth_url = service.get_auth_url()
    return jsonify({'auth_url': auth_url})

def _login_response(user_id, redirect_to):
    """Issue a JWT for `user_id` as an httpOnly cookie on a redirect."""
    frontend_url = current_app.config['CORS_ORIGINS'][0]
    response = make_response(redirect(redirect_to))
    response.set_cookie(
        'jwt_token',
        generate_jwt(user_id),
        httponly=True,
        secure=urlparse(frontend_url).scheme == 'https',
        samesite='Lax',
        max_age=current_app.config['JWT_EXPIRATION_HOURS'] * 3600,
        path='/'
    )
    return response


@bp.route('/callback', methods=['GET'])
def handle_callback():
    """Handle OAuth callback from Strava — logs in *or* links, per caller state."""
    from api.utils import get_current_user  # local: api.utils imports this module

    code = request.args.get('code')
    error = request.args.get('error')
    frontend_url = current_app.config['CORS_ORIGINS'][0]

    if error:
        return redirect(f"{frontend_url}/auth-error?error={error}")

    if not code:
        return redirect(f"{frontend_url}/auth-error?error=no_code")

    try:
        service = get_strava_service()
        token_data = service.exchange_code(code)

        athlete = token_data.get('athlete', {})
        scopes = request.args.get('scope')
        connections = ConnectionService()

        current_user = get_current_user()
        if current_user:
            # Logged in: attach Strava to this account (or refresh the link).
            connections.link_strava(current_user, athlete, token_data, scopes)
            user = current_user
        else:
            # Not logged in: existing connection logs that user in, otherwise
            # create the account — same UX as before.
            user = connections.find_or_create_from_strava(athlete, token_data, scopes)

        user.last_login = datetime.now(timezone.utc)
        user_repo.commit()

        # Kick off background Strava sync + training on login
        try:
            StravaSyncService().sync_user_async(user.id)
        except Exception as e:
            current_app.logger.error(f"Failed to start Strava sync for user {user.id}: {str(e)}")

        return _login_response(user.id, f"{frontend_url}/auth-success")

    except ConnectionConflictError as e:
        user_repo.rollback()
        current_app.logger.warning(f"Strava link conflict: {str(e)}")
        return redirect(f"{frontend_url}/auth-error?error=strava_already_linked")
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"Strava API error: {e.response.text}")
        return redirect(f"{frontend_url}/auth-error?error=exchange_failed")
    except Exception as e:
        current_app.logger.error(f"OAuth callback error: {str(e)}")
        return redirect(f"{frontend_url}/auth-error?error=exchange_failed")


def _magic_link_key(user):
    """Signing key for a magic link.

    Single-use without a token store: the key embeds the account's current
    `last_login`, so consuming a link rotates the key and invalidates every
    link issued before it (including a replay of the one just used).

    # ponytail: no jti table. Ceiling — we cannot revoke a *pending* link
    # without also logging the account in. Add a used-token table if we ever
    # need explicit revocation or "sign out everywhere".
    """
    marker = user.last_login.timestamp() if (user is not None and user.last_login) else 'signup'
    return f"{current_app.config['JWT_SECRET_KEY']}|magic_link|{marker}"


@bp.route('/magic-link', methods=['POST'])
def request_magic_link():
    """Email a login link. Always 202 — never reveals whether the account exists."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email or '@' not in email or len(email) > 255:
        return jsonify({'error': 'Valid email required'}), 400

    user = user_repo.find_one_by(email=email)
    # Strava-created accounts keep email_verified_at NULL: Strava never
    # verified that address for us, so a magic link must not adopt the account.
    if user is not None and user.email_verified_at is None:
        # TODO(identity #81 — see GH issues): this locks the user out of email login.
        # users.email is unique, so we can neither adopt the Strava-created row (takeover)
        # nor create a second one. Fix: let a signed-in user verify their address from
        # settings, which sets email_verified_at and unblocks this path.
        current_app.logger.info(f"Magic link suppressed for unverified account {user.id}")
    else:
        payload = {
            'email': email,
            'purpose': 'magic_link',
            'exp': datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
        }
        token = jwt.encode(payload, _magic_link_key(user), algorithm='HS256')
        # TODO(deploy-review #87 — see GH issues): link is http:// behind the Cloudflare tunnel.
        # url_for takes the scheme from the request; nginx rewrites X-Forwarded-Proto to http
        # and there's no ProxyFix. Fix: build it from FRONTEND_URL/PUBLIC_BASE_URL instead.
        link = url_for('auth.verify_magic_link', token=token, _external=True)
        send_email(
            email,
            'Your PaceMind sign-in link',
            f"Sign in to PaceMind:\n\n{link}\n\n"
            f"The link expires in {MAGIC_LINK_TTL_MINUTES} minutes and works once.\n"
            "If you did not request it, ignore this email."
        )

    return jsonify({'status': 'sent'}), 202


@bp.route('/magic-link/verify', methods=['GET'])
def verify_magic_link():
    """Consume a magic link: set the JWT cookie and redirect to the frontend."""
    frontend_url = current_app.config['CORS_ORIGINS'][0]
    token = request.args.get('token') or ''

    try:
        # The signing key depends on the account, so read the (still untrusted)
        # email first, then verify properly against that account's key.
        email = (jwt.decode(token, options={'verify_signature': False}).get('email') or '').strip().lower()
        user = user_repo.find_one_by(email=email) if email else None
        payload = jwt.decode(token, _magic_link_key(user), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return redirect(f"{frontend_url}/auth-error?error=link_expired")
    except jwt.InvalidTokenError:
        return redirect(f"{frontend_url}/auth-error?error=invalid_link")

    if payload.get('purpose') != 'magic_link' or payload.get('email') != email:
        return redirect(f"{frontend_url}/auth-error?error=invalid_link")

    now = datetime.now(timezone.utc)
    if user is None:
        user = User(email=email, auth_provider='email', email_verified_at=now)
        user_repo.create(user)
    elif user.email_verified_at is None:
        # Strava-created account holding this address — see request_magic_link
        # and TODO(identity #81).
        return redirect(f"{frontend_url}/auth-error?error=email_linked_to_strava")

    user.last_login = now  # rotates the signing key → the link is now spent
    user_repo.commit()

    return _login_response(user.id, f"{frontend_url}/auth-success")


@bp.route('/status', methods=['GET'])
def auth_status():
    """Check authentication status."""
    token = get_jwt_from_request()
    if not token:
        # Anonymous visitor: a normal answer, not an error (keeps the console clean).
        # A token that no longer verifies below is still a 401: that session dropped.
        return jsonify({'authenticated': False})

    user_id = verify_jwt(token)

    if not user_id:
        return jsonify({'authenticated': False}), 401

    user = user_repo.get_by_id(user_id)
    if not user:
        return jsonify({'authenticated': False}), 401

    try:
        StravaSyncService().sync_if_stale(user.id)
    except Exception:
        current_app.logger.exception('auto-sync check failed')

    return jsonify({
        'authenticated': True,
        'user': user.to_dict()
    })


@bp.route('/logout', methods=['POST'])
def logout():
    """Log out by clearing the JWT cookie."""
    frontend_url = current_app.config['CORS_ORIGINS'][0]
    is_secure = urlparse(frontend_url).scheme == 'https'
    response = make_response(jsonify({'message': 'Logged out'}))
    response.delete_cookie('jwt_token', path='/', secure=is_secure, samesite='Lax')
    return response


@bp.route('/refresh', methods=['POST'])
def refresh_strava_token():
    """Refresh Strava access token."""
    token = get_jwt_from_request()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = verify_jwt(token)

    if not user_id:
        return jsonify({'error': 'Invalid token'}), 401

    user = user_repo.get_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        service = get_strava_service()
        token_data = service.refresh_token(user.refresh_token)

        user_repo.update_tokens(user, token_data)
        user_repo.commit()

        return jsonify({'message': 'Token refreshed successfully'})

    except Exception as e:
        current_app.logger.error(f"Token refresh error: {str(e)}")
        return jsonify({'error': 'Failed to refresh token'}), 500


@bp.route('/connections', methods=['GET'])
def list_connections():
    """List the current user's provider connections."""
    from api.utils import get_current_user  # local: api.utils imports this module

    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    return jsonify({'connections': [c.to_dict() for c in user.connections]})


@bp.route('/connections/<provider>', methods=['DELETE'])
def disconnect_connection(provider):
    """Revoke a provider connection. The account and its activities survive."""
    from api.utils import get_current_user  # local: api.utils imports this module

    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    if not ConnectionService().disconnect(user, provider):
        return jsonify({'error': 'Not connected'}), 404

    user_repo.commit()
    return jsonify({'status': 'disconnected', 'provider': provider})

"""Billing API endpoints for subscription management.

Handles Stripe Checkout sessions, webhooks, and subscription status.
Supports: Premium monthly, Premium yearly, Race Day Pass.
"""

import hashlib
import os
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, current_app
from api.utils import get_current_user
from repositories import SubscriptionRepository, WaitlistRepository

logger = logging.getLogger(__name__)

billing_bp = Blueprint('billing', __name__, url_prefix='/api/billing')

subscription_repo = SubscriptionRepository()
waitlist_repo = WaitlistRepository()

# Stripe configuration (set in environment)
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_MONTHLY = os.environ.get('STRIPE_PRICE_MONTHLY', '')  # price_xxx
STRIPE_PRICE_YEARLY = os.environ.get('STRIPE_PRICE_YEARLY', '')    # price_xxx
STRIPE_PRICE_RACE_DAY = os.environ.get('STRIPE_PRICE_RACE_DAY', '') # price_xxx
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')


def _get_stripe():
    """Lazy import stripe to avoid crashes when not installed."""
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        return None


def requires_premium(feature=None):
    """Decorator to gate endpoints behind premium subscription.

    Usage:
        @requires_premium()                  # generic premium gate
        @requires_premium('race_report')     # gate with feature name (for contextual upgrade modal)
    """
    # Support both @requires_premium and @requires_premium('name')
    if callable(feature):
        f = feature
        return _build_premium_decorator(None)(f)

    return _build_premium_decorator(feature)


def _build_premium_decorator(feature_name):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'Authentication required'}), 401
            # Dev-mode bypass (consistent with training_plan dashboard logic)
            if os.environ.get('FLASK_ENV') == 'development':
                return f(*args, **kwargs)
            sub = subscription_repo.get_or_create(user.id)
            if not sub.is_premium:
                return jsonify({
                    'error': 'Premium subscription required',
                    'feature': feature_name,
                    'upgrade_url': '/pricing',
                    'checkout_url': '/api/billing/checkout',
                    'plan': sub.plan,
                    'agent_messages_remaining': sub.agent_messages_remaining,
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


@billing_bp.route('/status', methods=['GET'])
def get_status():
    """Get current subscription status."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    sub = subscription_repo.get_or_create(user.id)
    return jsonify(sub.to_dict())


@billing_bp.route('/checkout', methods=['POST'])
def create_checkout():
    """Create a Stripe Checkout session.

    Body: {"plan": "premium_monthly" | "premium_yearly" | "race_day_pass"}
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    stripe = _get_stripe()
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({'error': 'Stripe not configured'}), 503

    data = request.get_json() or {}
    plan = data.get('plan', 'premium_monthly')

    price_map = {
        'premium_monthly': STRIPE_PRICE_MONTHLY,
        'premium_yearly': STRIPE_PRICE_YEARLY,
        'race_day_pass': STRIPE_PRICE_RACE_DAY,
    }

    price_id = price_map.get(plan)
    if not price_id:
        return jsonify({'error': f'Unknown plan: {plan}'}), 400

    sub = subscription_repo.get_or_create(user.id)

    # Determine mode: subscription for recurring, payment for one-time
    mode = 'payment' if plan == 'race_day_pass' else 'subscription'

    try:
        if not sub.stripe_customer_id:
            customer = stripe.Customer.create(
                metadata={'user_id': str(user.id)},
            )
            sub.stripe_customer_id = customer.id
            subscription_repo.commit()

        session = stripe.checkout.Session.create(
            customer=sub.stripe_customer_id,
            mode=mode,
            line_items=[{'price': price_id, 'quantity': 1}],
            success_url=f'{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{FRONTEND_URL}/billing/cancel',
            metadata={
                'user_id': str(user.id),
                'plan': plan,
            },
        )
        return jsonify({'checkout_url': session.url, 'session_id': session.id})

    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        return jsonify({'error': 'Failed to create checkout session'}), 500


@billing_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhooks for payment events."""
    stripe = _get_stripe()
    if not stripe:
        return jsonify({'error': 'Stripe not configured'}), 503

    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event['type']
    data = event['data']['object']

    if event_type == 'checkout.session.completed':
        _handle_checkout_completed(data)
    elif event_type == 'customer.subscription.updated':
        _handle_subscription_updated(data)
    elif event_type == 'customer.subscription.deleted':
        _handle_subscription_deleted(data)

    return jsonify({'received': True})


VALID_CHECKOUT_PLANS = {'premium_monthly', 'premium_yearly', 'race_day_pass'}
RACE_DAY_PASS_DURATION = timedelta(days=7)

ALLOWED_WAITLIST_PLANS = {'coach_team', 'team', 'enterprise'}


def _hash_ip(ip: str) -> str:
    salt = current_app.config.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY', '')
    return hashlib.sha256(f"{ip}:{salt}".encode('utf-8')).hexdigest()[:32]


@billing_bp.route('/waitlist', methods=['POST'])
def join_waitlist():
    """Public waitlist signup (e.g. Coach/Team plan)."""
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    plan = (data.get('plan') or 'coach_team').strip().lower()
    source = (data.get('source') or '').strip()[:64] or None

    if not email or '@' not in email or len(email) > 255:
        return jsonify({'error': 'Valid email required'}), 400
    if plan not in ALLOWED_WAITLIST_PLANS:
        return jsonify({'error': 'Unknown plan'}), 400

    ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '') or '').split(',')[0].strip()
    user_agent = (request.headers.get('User-Agent') or '')[:255] or None
    ip_hash = _hash_ip(ip) if ip else None

    _signup, created = waitlist_repo.create_signup(
        email=email,
        plan=plan,
        source=source,
        ip_hash=ip_hash,
        user_agent=user_agent,
    )
    waitlist_repo.commit()

    logger.info(f"Waitlist signup: plan={plan} email={email} created={created}")
    return jsonify({
        'status': 'joined',
        'plan': plan,
        'already_joined': not created,
    })


@billing_bp.route('/cancel', methods=['POST'])
def cancel_subscription():
    """Cancel the current subscription."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    stripe = _get_stripe()
    if not stripe:
        return jsonify({'error': 'Stripe not configured'}), 503

    sub = subscription_repo.get_or_create(user.id)

    if not sub.stripe_subscription_id:
        return jsonify({'error': 'No active subscription to cancel'}), 400

    try:
        # Cancel at period end (user keeps access until expiry).
        # Don't mutate sub.status here — that would flip is_premium to False
        # immediately, denying access the user already paid for. Stripe will
        # send customer.subscription.deleted at period end; that handler
        # transitions status to 'expired' and plan to 'free'.
        stripe.Subscription.modify(
            sub.stripe_subscription_id,
            cancel_at_period_end=True,
        )
        sub.canceled_at = datetime.now(timezone.utc)
        subscription_repo.commit()

        return jsonify({'message': 'Subscription will cancel at end of billing period'})

    except Exception as e:
        logger.error(f"Stripe cancel error: {e}")
        return jsonify({'error': 'Failed to cancel subscription'}), 500


def _handle_checkout_completed(session):
    """Process successful checkout.

    Stripe webhook delivery is at-least-once, so this handler must be
    idempotent. Race day pass expiry is anchored on the session's `created`
    timestamp (set by Stripe at session-creation time) rather than `now`,
    so a redelivered event computes the same `expires_at`.
    """
    metadata = session.get('metadata') or {}
    user_id_raw = metadata.get('user_id')
    plan = metadata.get('plan')

    if not user_id_raw:
        logger.warning("Checkout completed without user_id metadata")
        return
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        logger.error("Checkout completed with non-integer user_id metadata: %r", user_id_raw)
        return
    if plan not in VALID_CHECKOUT_PLANS:
        logger.error("Checkout completed with unknown plan metadata: %r (user_id=%s)", plan, user_id)
        return

    sub = subscription_repo.get_or_create(user_id)
    sub.plan = plan
    sub.status = 'active'

    session_created = session.get('created')
    if session_created:
        anchor = datetime.fromtimestamp(session_created, tz=timezone.utc)
    else:
        anchor = datetime.now(timezone.utc)
    sub.started_at = anchor

    if plan == 'race_day_pass':
        sub.expires_at = anchor + RACE_DAY_PASS_DURATION
    elif session.get('subscription'):
        sub.stripe_subscription_id = session['subscription']
        # Subscription expiry managed by Stripe webhooks

    subscription_repo.commit()
    logger.info(f"User {user_id} activated plan: {plan}")


def _handle_subscription_updated(subscription):
    """Handle subscription status changes."""
    stripe_sub_id = subscription.get('id')
    sub = subscription_repo.get_by_stripe_subscription(stripe_sub_id)

    if not sub:
        return

    status = subscription.get('status')
    if status == 'active':
        sub.status = 'active'
    elif status == 'past_due':
        sub.status = 'past_due'
    elif status in ('canceled', 'unpaid'):
        sub.status = 'expired'
        sub.plan = 'free'

    # Update expiry from Stripe period end
    period_end = subscription.get('current_period_end')
    if period_end:
        sub.expires_at = datetime.fromtimestamp(period_end, tz=timezone.utc)

    subscription_repo.commit()


def _handle_subscription_deleted(subscription):
    """Handle subscription cancellation/deletion."""
    stripe_sub_id = subscription.get('id')
    sub = subscription_repo.get_by_stripe_subscription(stripe_sub_id)

    if not sub:
        return

    sub.status = 'expired'
    sub.plan = 'free'
    sub.stripe_subscription_id = None
    subscription_repo.commit()
    logger.info(f"Subscription {stripe_sub_id} deleted, user reverted to free")

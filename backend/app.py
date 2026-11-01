import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
from flask import Flask, jsonify
from flask_cors import CORS
from config import Config
from database import db, init_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

def create_app(config_class=Config):
    """Application factory."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, instance_path=os.path.join(base_dir, "instance"))
    # '/api/routes' must not 308 to '/api/routes/': behind a proxy the absolute
    # Location loses port/scheme, and an http:// redirect from an https page is blocked.
    app.url_map.strict_slashes = False
    app.config.from_object(config_class)

    # Initialize extensions
    CORS(app, supports_credentials=True, origins=app.config['CORS_ORIGINS'])
    init_db(app)

    # Initialize Sentry (if configured)
    sentry_dsn = os.getenv('SENTRY_DSN')
    if sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)
        except ImportError:
            app.logger.warning("SENTRY_DSN set but sentry-sdk not installed")

    # Initialize rate limiter
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(
            get_remote_address,
            app=app,
            default_limits=["60 per minute"],
            storage_uri="memory://",
        )
        app.limiter = limiter
    except ImportError:
        app.logger.warning("Flask-Limiter not installed, rate limiting disabled")

    # Initialize Flask-Migrate
    try:
        from flask_migrate import Migrate
        migrate = Migrate(app, db, directory=os.path.join(base_dir, "migrations"))
    except ImportError:
        pass  # Flask-Migrate not installed, migrations unavailable

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if os.getenv('FLASK_ENV') == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Register blueprints
    from api import activities, auth, gpx, strava, prediction, performance, physics, hybrid, agent, demo
    from api.billing import billing_bp
    from api.training_plan import bp as training_plan_bp
    from api.weather import weather_bp
    from api.notifications import bp as notifications_bp
    from api.routes import bp as routes_bp
    from api.races import bp as races_bp
    from api.mcp import bp as mcp_bp
    app.register_blueprint(activities.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(gpx.bp)
    app.register_blueprint(strava.bp)
    app.register_blueprint(prediction.bp)
    app.register_blueprint(performance.bp)
    app.register_blueprint(physics.bp)
    app.register_blueprint(hybrid.bp)
    app.register_blueprint(agent.bp)
    app.register_blueprint(demo.bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(training_plan_bp)
    app.register_blueprint(weather_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(races_bp)
    app.register_blueprint(mcp_bp)

    # Tighter per-IP limits on the magic-link endpoints: they send email and
    # they are the one auth path that needs no prior account.
    if hasattr(app, 'limiter'):
        for endpoint, limit in (('auth.request_magic_link', '10 per hour'),
                                ('auth.verify_magic_link', '30 per hour')):
            app.view_functions[endpoint] = app.limiter.limit(limit)(app.view_functions[endpoint])

    @app.route('/api/health')
    def health():
        db_ok = False
        try:
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            db_ok = True
        except Exception:
            pass
        status = 'ok' if db_ok else 'degraded'
        code = 200 if db_ok else 503
        return jsonify({'status': status, 'database': db_ok}), code

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)

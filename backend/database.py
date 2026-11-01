from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def init_db(app):
    """Initialize database with app context."""
    db.init_app(app)

    # Import the models package to register all models on db.metadata.
    # models/__init__.py re-exports every model, so new models are
    # automatically visible to Alembic without touching this file.
    import models  # noqa: F401

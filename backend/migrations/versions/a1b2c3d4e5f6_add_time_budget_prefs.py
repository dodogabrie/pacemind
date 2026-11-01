"""add time-budget fields to user_training_preferences

Revision ID: a1b2c3d4e5f6
Revises: f8a9c2e1b340
Create Date: 2026-04-29 22:30:00.000000

Idempotent: each ADD COLUMN is guarded so a re-run on already-migrated DBs
(or hand-applied schemas) is a no-op. Pattern matches the rest of the
migration set.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f8a9c2e1b340'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('available_hours_per_week', sa.Float()),
    ('usual_midweek_hours', sa.Float()),
    ('max_mountain_hours_per_outing', sa.Float()),
)


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        # Bare DB — the model definition will materialise the table on
        # first request via init_db(). Nothing to add here.
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, col_type in NEW_COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in existing:
                batch_op.drop_column(name)

"""add pace_zone_method + reference race to user_training_preferences

Revision ID: j1a2b3c4d5e9
Revises: i1a2b3c4d5e8
Create Date: 2026-05-23 12:00:00.000000

Idempotent: each ADD COLUMN is guarded so a re-run on already-migrated DBs
(or hand-applied schemas) is a no-op. Pattern matches the rest of the
migration set.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'j1a2b3c4d5e9'
down_revision = 'i1a2b3c4d5e8'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('pace_zone_method', sa.String(length=16), "'physics'"),
    ('pace_zone_race_distance_m', sa.Float(), None),
    ('pace_zone_race_time_s', sa.Float(), None),
)


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        # Bare DB — the model definition materialises the table on first
        # request via init_db(). Nothing to add here.
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, col_type, default in NEW_COLUMNS:
            if name not in existing:
                batch_op.add_column(
                    sa.Column(name, col_type, nullable=True,
                              server_default=sa.text(default) if default else None)
                )


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, _, _ in NEW_COLUMNS:
            if name in existing:
                batch_op.drop_column(name)

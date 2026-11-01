"""extend training preferences and training plan warnings

Revision ID: c7d89a1f2b34
Revises: b5e2f4a1c0d8
Create Date: 2026-04-28 09:30:00.000000

Adds capacity caps and mountain budget fields to user_training_preferences,
plus a warnings JSON column to training_plans for feasibility output.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'c7d89a1f2b34'
down_revision = 'b5e2f4a1c0d8'
branch_labels = None
depends_on = None


PREF_COLUMNS = (
    ('max_weekly_km', sa.Float(), True, None),
    ('max_long_run_km', sa.Float(), True, None),
    ('max_long_run_hours', sa.Float(), True, None),
    ('mountain_access_per_week', sa.Float(), True, None),
    ('mountain_access_per_month', sa.Integer(), True, None),
    ('max_mountain_elevation_m', sa.Integer(), True, None),
    ('max_mountain_distance_km', sa.Float(), True, None),
    ('sample_mountain_route_id', sa.Integer(), True, None),
    ('terrain_profile', sa.String(length=32), True, None),
    ('terrain_profile_source', sa.String(length=16), True, 'inferred'),
)


def _has_column(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade():
    conn = op.get_bind()

    for name, col_type, nullable, default in PREF_COLUMNS:
        if _has_column(conn, 'user_training_preferences', name):
            continue
        kwargs = {'nullable': nullable}
        if default is not None:
            kwargs['server_default'] = default
        op.add_column(
            'user_training_preferences',
            sa.Column(name, col_type, **kwargs),
        )

    # FK from sample_mountain_route_id -> training_routes.id (SET NULL on delete)
    # Skip on SQLite — ALTER TABLE for FK is awkward and integrity is enforced at app layer.
    if conn.dialect.name != 'sqlite':
        try:
            op.create_foreign_key(
                'fk_user_training_prefs_sample_route',
                'user_training_preferences',
                'training_routes',
                ['sample_mountain_route_id'],
                ['id'],
                ondelete='SET NULL',
            )
        except Exception:
            # Already exists or table missing — ignore.
            pass

    if not _has_column(conn, 'training_plans', 'warnings'):
        op.add_column(
            'training_plans',
            sa.Column('warnings', sa.JSON(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()

    if _has_column(conn, 'training_plans', 'warnings'):
        op.drop_column('training_plans', 'warnings')

    if conn.dialect.name != 'sqlite':
        try:
            op.drop_constraint(
                'fk_user_training_prefs_sample_route',
                'user_training_preferences',
                type_='foreignkey',
            )
        except Exception:
            pass

    for name, _ct, _nullable, _default in reversed(PREF_COLUMNS):
        if _has_column(conn, 'user_training_preferences', name):
            op.drop_column('user_training_preferences', name)

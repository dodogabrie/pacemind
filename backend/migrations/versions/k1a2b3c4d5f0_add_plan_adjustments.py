"""add plan_adjustments audit table

Revision ID: k1a2b3c4d5f0
Revises: j1a2b3c4d5e9
Create Date: 2026-05-23 14:00:00.000000

Idempotent: table + index creation are guarded so a re-run on an
already-migrated DB (or a hand-applied schema) is a no-op. Pattern matches the
rest of the migration set (see i1a2b3c4d5e8).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'k1a2b3c4d5f0'
down_revision = 'j1a2b3c4d5e9'
branch_labels = None
depends_on = None


def _has_table(conn, table: str) -> bool:
    return table in inspect(conn).get_table_names()


def _has_index(conn, table: str, index_name: str) -> bool:
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return False
    return index_name in {ix['name'] for ix in insp.get_indexes(table)}


def upgrade():
    conn = op.get_bind()
    if not _has_table(conn, 'plan_adjustments'):
        op.create_table(
            'plan_adjustments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('plan_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('applied_at', sa.DateTime(), nullable=False),
            sa.Column('kind', sa.String(length=16), nullable=False),
            sa.Column('trigger', sa.String(length=16), nullable=False),
            sa.Column('day_before', sa.String(length=16), nullable=True),
            sa.Column('day_after', sa.String(length=16), nullable=True),
            sa.Column('workout_type_before', sa.String(length=32), nullable=True),
            sa.Column('workout_type_after', sa.String(length=32), nullable=True),
            sa.Column('checkin_id', sa.Integer(), nullable=True),
            sa.Column('payload_json', sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(['plan_id'], ['training_plans.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['checkin_id'], ['daily_checkins.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _has_index(conn, 'plan_adjustments', 'ix_plan_adjustment_plan_applied'):
        op.create_index(
            'ix_plan_adjustment_plan_applied',
            'plan_adjustments',
            ['plan_id', 'applied_at'],
        )
    if not _has_index(conn, 'plan_adjustments', 'ix_plan_adjustment_user_applied'):
        op.create_index(
            'ix_plan_adjustment_user_applied',
            'plan_adjustments',
            ['user_id', 'applied_at'],
        )


def downgrade():
    conn = op.get_bind()
    if _has_index(conn, 'plan_adjustments', 'ix_plan_adjustment_user_applied'):
        op.drop_index('ix_plan_adjustment_user_applied', table_name='plan_adjustments')
    if _has_index(conn, 'plan_adjustments', 'ix_plan_adjustment_plan_applied'):
        op.drop_index('ix_plan_adjustment_plan_applied', table_name='plan_adjustments')
    if _has_table(conn, 'plan_adjustments'):
        op.drop_table('plan_adjustments')

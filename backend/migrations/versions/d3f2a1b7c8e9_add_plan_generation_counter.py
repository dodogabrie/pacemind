"""add plan generation counter to subscriptions

Revision ID: d3f2a1b7c8e9
Revises: c21c14348c44
Create Date: 2026-04-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'd3f2a1b7c8e9'
down_revision = 'c21c14348c44'
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade():
    conn = op.get_bind()
    if not _has_column(conn, 'user_subscriptions', 'plan_generations_this_period'):
        op.add_column(
            'user_subscriptions',
            sa.Column('plan_generations_this_period', sa.Integer(), nullable=True, server_default='0'),
        )
    if not _has_column(conn, 'user_subscriptions', 'plan_generations_reset_date'):
        op.add_column(
            'user_subscriptions',
            sa.Column('plan_generations_reset_date', sa.Date(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, 'user_subscriptions', 'plan_generations_reset_date'):
        op.drop_column('user_subscriptions', 'plan_generations_reset_date')
    if _has_column(conn, 'user_subscriptions', 'plan_generations_this_period'):
        op.drop_column('user_subscriptions', 'plan_generations_this_period')

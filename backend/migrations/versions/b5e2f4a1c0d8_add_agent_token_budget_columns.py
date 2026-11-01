"""add agent token budget columns to user_subscriptions

Revision ID: b5e2f4a1c0d8
Revises: a4f1c2d83b71
Create Date: 2026-04-27 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'b5e2f4a1c0d8'
down_revision = 'a4f1c2d83b71'
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return False
    return column in {c['name'] for c in inspector.get_columns(table)}


def upgrade():
    conn = op.get_bind()
    if not _has_column(conn, 'user_subscriptions', 'agent_input_tokens_today'):
        op.add_column(
            'user_subscriptions',
            sa.Column('agent_input_tokens_today', sa.Integer(), nullable=True, server_default='0'),
        )
    if not _has_column(conn, 'user_subscriptions', 'agent_output_tokens_today'):
        op.add_column(
            'user_subscriptions',
            sa.Column('agent_output_tokens_today', sa.Integer(), nullable=True, server_default='0'),
        )
    if not _has_column(conn, 'user_subscriptions', 'agent_tokens_reset_date'):
        op.add_column(
            'user_subscriptions',
            sa.Column('agent_tokens_reset_date', sa.Date(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    for col in ('agent_tokens_reset_date', 'agent_output_tokens_today', 'agent_input_tokens_today'):
        if _has_column(conn, 'user_subscriptions', col):
            op.drop_column('user_subscriptions', col)

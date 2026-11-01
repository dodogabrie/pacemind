"""add context_type and title to agent_conversations

Revision ID: h1a2b3c4d5e7
Revises: ed921de2e038
Create Date: 2026-05-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'h1a2b3c4d5e7'
down_revision = 'ed921de2e038'
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def _has_index(conn, table: str, index_name: str) -> bool:
    insp = inspect(conn)
    if table not in insp.get_table_names():
        return False
    return index_name in {ix['name'] for ix in insp.get_indexes(table)}


def upgrade():
    conn = op.get_bind()
    insp = inspect(conn)
    if 'agent_conversations' not in insp.get_table_names():
        return

    if not _has_column(conn, 'agent_conversations', 'context_type'):
        op.add_column(
            'agent_conversations',
            sa.Column('context_type', sa.String(length=32), nullable=True),
        )
    if not _has_column(conn, 'agent_conversations', 'title'):
        op.add_column(
            'agent_conversations',
            sa.Column('title', sa.String(length=120), nullable=True),
        )
    if not _has_index(conn, 'agent_conversations', 'ix_agent_conversations_context_type'):
        op.create_index(
            'ix_agent_conversations_context_type',
            'agent_conversations',
            ['context_type'],
        )


def downgrade():
    conn = op.get_bind()
    insp = inspect(conn)
    if 'agent_conversations' not in insp.get_table_names():
        return
    if _has_index(conn, 'agent_conversations', 'ix_agent_conversations_context_type'):
        op.drop_index(
            'ix_agent_conversations_context_type',
            table_name='agent_conversations',
        )
    if _has_column(conn, 'agent_conversations', 'title'):
        op.drop_column('agent_conversations', 'title')
    if _has_column(conn, 'agent_conversations', 'context_type'):
        op.drop_column('agent_conversations', 'context_type')

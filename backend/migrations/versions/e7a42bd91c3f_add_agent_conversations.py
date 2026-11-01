"""add agent_conversations

Revision ID: e7a42bd91c3f
Revises: d3f2a1b7c8e9
Create Date: 2026-04-24 22:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'e7a42bd91c3f'
down_revision = 'd3f2a1b7c8e9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'agent_conversations' in inspector.get_table_names():
        return

    op.create_table(
        'agent_conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('messages', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'conversation_id', name='uq_agent_conv_user_conv'),
    )
    op.create_index(
        'ix_agent_conv_user_last_active',
        'agent_conversations',
        ['user_id', 'last_active_at'],
    )


def downgrade():
    op.drop_index('ix_agent_conv_user_last_active', table_name='agent_conversations')
    op.drop_table('agent_conversations')

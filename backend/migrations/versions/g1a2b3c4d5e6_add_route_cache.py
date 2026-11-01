"""add route_cache table

Revision ID: g1a2b3c4d5e6
Revises: f8a9c2e1b340
Create Date: 2026-04-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'g1a2b3c4d5e6'
down_revision = 'f8a9c2e1b340'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'route_cache' not in inspector.get_table_names():
        op.create_table(
            'route_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('cache_key', sa.String(length=64), nullable=False),
            sa.Column('data', sa.JSON(), nullable=False),
            sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('cache_key', name='uq_route_cache_key'),
        )
        op.create_index('ix_route_cache_cache_key', 'route_cache', ['cache_key'])
        op.create_index('ix_route_cache_expires_at', 'route_cache', ['expires_at'])


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'route_cache' in inspector.get_table_names():
        op.drop_index('ix_route_cache_expires_at', table_name='route_cache')
        op.drop_index('ix_route_cache_cache_key', table_name='route_cache')
        op.drop_table('route_cache')

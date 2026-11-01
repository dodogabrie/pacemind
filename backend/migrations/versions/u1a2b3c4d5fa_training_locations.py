"""training_locations table

Revision ID: u1a2b3c4d5fa
Revises: t1a2b3c4d5f9
Create Date: 2026-10-25 12:00:00.000000

Places the user trains from, each owning some weekdays (GH #120).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = 'u1a2b3c4d5fa'
down_revision = 't1a2b3c4d5f9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if 'training_locations' in inspect(conn).get_table_names():
        return
    op.create_table(
        'training_locations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lon', sa.Float(), nullable=False),
        sa.Column('radius_km', sa.Float(), nullable=False),
        sa.Column('weekdays', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_training_locations_user_id', 'training_locations', ['user_id'])


def downgrade():
    conn = op.get_bind()
    if 'training_locations' in inspect(conn).get_table_names():
        op.drop_table('training_locations')

"""add user_training_preferences

Revision ID: c21c14348c44
Revises: 0001
Create Date: 2026-03-24 21:30:51.268664

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'c21c14348c44'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent guard: skip if table already exists
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        op.create_table('user_training_preferences',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('long_run_day', sa.String(length=16), nullable=True),
            sa.Column('back_to_back', sa.Boolean(), nullable=True),
            sa.Column('rest_days', sa.JSON(), nullable=True),
            sa.Column('mountain_days', sa.JSON(), nullable=True),
            sa.Column('max_hours_per_day', sa.Float(), nullable=True),
            sa.Column('strength_training_days', sa.Integer(), nullable=True),
            sa.Column('strength_preferred_days', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )


def downgrade():
    op.drop_table('user_training_preferences')

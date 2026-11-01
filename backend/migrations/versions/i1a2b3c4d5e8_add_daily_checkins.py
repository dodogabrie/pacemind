"""add daily_checkins table

Revision ID: i1a2b3c4d5e8
Revises: h1a2b3c4d5e7
Create Date: 2026-05-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'i1a2b3c4d5e8'
down_revision = 'h1a2b3c4d5e7'
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
    if not _has_table(conn, 'daily_checkins'):
        op.create_table(
            'daily_checkins',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('rpe_yesterday', sa.Integer(), nullable=True),
            sa.Column('feeling', sa.String(length=16), nullable=True),
            sa.Column('sleep_h', sa.Float(), nullable=True),
            sa.Column('soreness', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'date', name='uq_daily_checkin_user_date'),
        )
    if not _has_index(conn, 'daily_checkins', 'ix_daily_checkin_user_date'):
        op.create_index(
            'ix_daily_checkin_user_date',
            'daily_checkins',
            ['user_id', 'date'],
        )


def downgrade():
    conn = op.get_bind()
    if _has_index(conn, 'daily_checkins', 'ix_daily_checkin_user_date'):
        op.drop_index('ix_daily_checkin_user_date', table_name='daily_checkins')
    if _has_table(conn, 'daily_checkins'):
        op.drop_table('daily_checkins')

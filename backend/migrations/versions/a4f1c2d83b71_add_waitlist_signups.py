"""add waitlist_signups

Revision ID: a4f1c2d83b71
Revises: e7a42bd91c3f
Create Date: 2026-04-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'a4f1c2d83b71'
down_revision = 'e7a42bd91c3f'
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _table_exists('waitlist_signups'):
        op.create_table(
            'waitlist_signups',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('plan', sa.String(length=32), nullable=False),
            sa.Column('source', sa.String(length=64), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column('ip_hash', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('email', 'plan', name='uq_waitlist_email_plan'),
        )
        op.create_index('ix_waitlist_signups_email', 'waitlist_signups', ['email'])
        op.create_index('ix_waitlist_plan_created', 'waitlist_signups', ['plan', 'created_at'])


def downgrade():
    op.drop_index('ix_waitlist_plan_created', table_name='waitlist_signups')
    op.drop_index('ix_waitlist_signups_email', table_name='waitlist_signups')
    op.drop_table('waitlist_signups')

"""add ftp_w to user_training_preferences

Revision ID: m1a2b3c4d5f2
Revises: l1a2b3c4d5f1
Create Date: 2026-05-23 14:00:00.000000

Idempotent: the ADD COLUMN is guarded so a re-run on already-migrated DBs
(or hand-applied schemas) is a no-op. Pattern matches the rest of the
migration set.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'm1a2b3c4d5f2'
down_revision = 'l1a2b3c4d5f1'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('ftp_w', sa.Integer()),
)


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        # Bare DB — the model definition materialises the table on first
        # request via init_db(). Nothing to add here.
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, col_type in NEW_COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'user_training_preferences' not in inspector.get_table_names():
        return

    existing = {c['name'] for c in inspector.get_columns('user_training_preferences')}
    with op.batch_alter_table('user_training_preferences') as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in existing:
                batch_op.drop_column(name)

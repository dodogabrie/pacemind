"""add user_connections + decouple users from Strava identity

Revision ID: o1a2b3c4d5f4
Revises: n1a2b3c4d5f3
Create Date: 2026-08-21 09:00:00.000000

Four steps, each independently guarded so a re-run (or a hand-applied schema)
is a no-op:

1. create `user_connections`
2. backfill one strava connection per user that has a strava_user_id — the
   token columns are already-encrypted LargeBinary and are copied **verbatim**;
   decrypting/re-encrypting here would silently log everyone out of Strava if
   the key ever differed between this process and the app.
3. `users.strava_user_id` -> nullable (email accounts have no Strava id)
4. new `users` columns: password_hash, auth_provider, email_verified_at

Downgrade drops the new table only. The three new `users` columns hold real
data (an email account's whole identity) and are left in place — an old
codebase simply ignores them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'o1a2b3c4d5f4'
down_revision = 'n1a2b3c4d5f3'
branch_labels = None
depends_on = None


NEW_USER_COLUMNS = (
    ('password_hash', sa.String(length=255), None),
    ('auth_provider', sa.String(length=32), 'strava'),
    ('email_verified_at', sa.DateTime(), None),
)


def _table_exists(conn, table: str) -> bool:
    return table in inspect(conn).get_table_names()


def _columns(conn, table: str) -> dict:
    return {c['name']: c for c in inspect(conn).get_columns(table)}


def upgrade():
    conn = op.get_bind()

    # 1. user_connections
    if not _table_exists(conn, 'user_connections'):
        op.create_table(
            'user_connections',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('provider', sa.String(length=32), nullable=False),
            sa.Column('external_user_id', sa.String(length=128), nullable=False),
            sa.Column('access_token', sa.LargeBinary(), nullable=True),
            sa.Column('refresh_token', sa.LargeBinary(), nullable=True),
            sa.Column('expires_at', sa.Integer(), nullable=True),
            sa.Column('scopes', sa.String(length=512), nullable=True),
            sa.Column('connected_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_at', sa.DateTime(), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('provider', 'external_user_id',
                                name='uq_connection_provider_external'),
            sa.UniqueConstraint('user_id', 'provider',
                                name='uq_connection_user_provider'),
        )

    if not _table_exists(conn, 'users'):
        # Bare DB — init_db() materialises everything from the models.
        return

    # 2. backfill (raw bytes, no crypto)
    conn.execute(sa.text(
        "INSERT INTO user_connections "
        "  (user_id, provider, external_user_id, access_token, refresh_token, "
        "   expires_at, connected_at, status) "
        "SELECT u.id, 'strava', CAST(u.strava_user_id AS VARCHAR), u.access_token, "
        "       u.refresh_token, u.expires_at, u.created_at, 'active' "
        "FROM users u "
        "WHERE u.strava_user_id IS NOT NULL "
        "  AND NOT EXISTS (SELECT 1 FROM user_connections c "
        "                  WHERE c.user_id = u.id AND c.provider = 'strava')"
    ))

    # 3 + 4. users columns, in one table rebuild (SQLite rebuilds on ALTER)
    existing = _columns(conn, 'users')
    needs_nullable = not existing['strava_user_id']['nullable']
    missing = [c for c in NEW_USER_COLUMNS if c[0] not in existing]
    if not needs_nullable and not missing:
        return

    with op.batch_alter_table('users') as batch_op:
        if needs_nullable:
            batch_op.alter_column('strava_user_id', existing_type=sa.Integer(),
                                  nullable=True)
        for name, col_type, default in missing:
            batch_op.add_column(sa.Column(name, col_type, nullable=True,
                                          server_default=default))


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, 'user_connections'):
        op.drop_table('user_connections')
    # strava_user_id stays nullable: email accounts have no id to put back, so
    # restoring NOT NULL would fail on exactly the rows this migration enabled.
    # The three new users columns are data-bearing and are deliberately kept.

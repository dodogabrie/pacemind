"""add races table + training_plans.race_id

Revision ID: f8a9c2e1b340
Revises: c7d89a1f2b34
Create Date: 2026-04-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'f8a9c2e1b340'
down_revision = 'c7d89a1f2b34'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'races' not in inspector.get_table_names():
        op.create_table(
            'races',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('source', sa.String(length=16), nullable=False, server_default='seed'),
            sa.Column('external_id', sa.String(length=128), nullable=True),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=255), nullable=False),
            sa.Column('url', sa.String(length=512), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('country', sa.String(length=2), nullable=True),
            sa.Column('region', sa.String(length=128), nullable=True),
            sa.Column('location', sa.String(length=255), nullable=True),
            sa.Column('lat', sa.Float(), nullable=True),
            sa.Column('lon', sa.Float(), nullable=True),
            sa.Column('distance_km', sa.Float(), nullable=False),
            sa.Column('elev_gain_m', sa.Float(), nullable=True),
            sa.Column('elev_loss_m', sa.Float(), nullable=True),
            sa.Column('surface', sa.String(length=16), nullable=True),
            sa.Column('race_type', sa.String(length=16), nullable=True),
            sa.Column('itra_points', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug', name='uq_race_slug'),
            sa.UniqueConstraint('source', 'external_id', name='uq_race_source_external'),
        )
        op.create_index('ix_races_date', 'races', ['date'])
        op.create_index('ix_races_country', 'races', ['country'])
        op.create_index('ix_race_date_country', 'races', ['date', 'country'])
        op.create_index('ix_race_distance', 'races', ['distance_km'])

    # training_plans.race_id — guarded
    cols = {c['name'] for c in inspector.get_columns('training_plans')} \
        if 'training_plans' in inspector.get_table_names() else set()
    if 'race_id' not in cols:
        with op.batch_alter_table('training_plans') as batch_op:
            batch_op.add_column(
                sa.Column('race_id', sa.Integer(), nullable=True)
            )
            batch_op.create_foreign_key(
                'fk_training_plans_race_id',
                'races',
                ['race_id'],
                ['id'],
            )
            batch_op.create_index('ix_training_plans_race_id', ['race_id'])


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'training_plans' in inspector.get_table_names():
        cols = {c['name'] for c in inspector.get_columns('training_plans')}
        if 'race_id' in cols:
            with op.batch_alter_table('training_plans') as batch_op:
                batch_op.drop_index('ix_training_plans_race_id')
                batch_op.drop_constraint('fk_training_plans_race_id', type_='foreignkey')
                batch_op.drop_column('race_id')

    if 'races' in inspector.get_table_names():
        op.drop_index('ix_race_distance', table_name='races')
        op.drop_index('ix_race_date_country', table_name='races')
        op.drop_index('ix_races_country', table_name='races')
        op.drop_index('ix_races_date', table_name='races')
        op.drop_table('races')

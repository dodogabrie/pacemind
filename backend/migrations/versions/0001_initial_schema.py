"""initial schema — consolidated

Revision ID: 0001
Revises:
Create Date: 2026-03-08 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name):
    return name in sa_inspect(op.get_bind()).get_table_names()


def _index_exists(table, index_name):
    indexes = sa_inspect(op.get_bind()).get_indexes(table)
    return any(idx['name'] == index_name for idx in indexes)


def _column_exists(table, column):
    columns = [c['name'] for c in sa_inspect(op.get_bind()).get_columns(table)]
    return column in columns


def upgrade():
    # ── users (hub table, no FKs) ──
    if not _table_exists('users'):
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(255), nullable=True),
            sa.Column('strava_user_id', sa.Integer(), nullable=False),
            sa.Column('strava_username', sa.String(255), nullable=True),
            sa.Column('access_token', sa.LargeBinary(), nullable=True),
            sa.Column('refresh_token', sa.LargeBinary(), nullable=True),
            sa.Column('expires_at', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('last_login', sa.DateTime(), nullable=True),
            sa.Column('user_endurance_score', sa.Float(), nullable=True),
            sa.Column('user_recovery_rate', sa.Float(), nullable=True),
            sa.Column('user_base_fitness', sa.Float(), nullable=True),
            sa.Column('fingerprint_calibrated_at', sa.DateTime(), nullable=True),
            sa.Column('fingerprint_activity_count', sa.Integer(), nullable=True),
            sa.Column('saved_flat_pace', sa.Float(), nullable=True),
            sa.Column('saved_anchor_ratios', sa.JSON(), nullable=True),
            sa.Column('calibration_updated_at', sa.DateTime(), nullable=True),
            sa.Column('calibration_activity_id', sa.Integer(), nullable=True),
            sa.Column('physics_params', sa.JSON(), nullable=True),
            sa.Column('training_base_lat', sa.Float(), nullable=True),
            sa.Column('training_base_lon', sa.Float(), nullable=True),
            sa.Column('training_base_name', sa.String(255), nullable=True),
            sa.Column('training_travel_radius_km', sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('email'),
            sa.UniqueConstraint('strava_user_id'),
        )

    # ── tables with FK → users only ──
    if not _table_exists('agent_param_snapshots'):
        op.create_table('agent_param_snapshots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('params_snapshot', sa.JSON(), nullable=False),
            sa.Column('action', sa.String(64), nullable=False),
            sa.Column('description', sa.String(256), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('evaluation_status'):
        op.create_table('evaluation_status',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(50), nullable=False),
            sa.Column('current_step', sa.String(100), nullable=True),
            sa.Column('total_steps', sa.Integer(), nullable=True),
            sa.Column('current_step_number', sa.Integer(), nullable=True),
            sa.Column('total_activities', sa.Integer(), nullable=True),
            sa.Column('training_activities', sa.Integer(), nullable=True),
            sa.Column('target_activity_id', sa.String(50), nullable=True),
            sa.Column('target_activity_name', sa.String(255), nullable=True),
            sa.Column('total_segments', sa.Integer(), nullable=True),
            sa.Column('processed_segments', sa.Integer(), nullable=True),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )

    if not _table_exists('gpx_files'):
        op.create_table('gpx_files',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('original_filename', sa.String(255), nullable=False),
            sa.Column('file_path', sa.String(512), nullable=False),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.Column('upload_date', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('performance_snapshots'):
        op.create_table('performance_snapshots',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('snapshot_date', sa.DateTime(), nullable=False),
            sa.Column('period_type', sa.String(20), nullable=False),
            sa.Column('period_start', sa.DateTime(), nullable=False),
            sa.Column('period_end', sa.DateTime(), nullable=False),
            sa.Column('flat_pace', sa.Float(), nullable=False),
            sa.Column('anchor_ratios', sa.JSON(), nullable=False),
            sa.Column('activity_count', sa.Integer(), nullable=False),
            sa.Column('total_distance_km', sa.Float(), nullable=True),
            sa.Column('total_elevation_m', sa.Float(), nullable=True),
            sa.Column('fatigue_curve', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('strava_activities'):
        op.create_table('strava_activities',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('strava_id', sa.BigInteger(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('distance', sa.Float(), nullable=False),
            sa.Column('start_date', sa.DateTime(), nullable=False),
            sa.Column('streams', sa.JSON(), nullable=True),
            sa.Column('downloaded_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('strava_activity_cache'):
        op.create_table('strava_activity_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('activities', sa.JSON(), nullable=False),
            sa.Column('fetched_at', sa.DateTime(), nullable=False),
            sa.Column('after_timestamp', sa.Integer(), nullable=True),
            sa.Column('activity_count', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('sync_status'):
        op.create_table('sync_status',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(50), nullable=False),
            sa.Column('current_step', sa.String(100), nullable=True),
            sa.Column('total_activities', sa.Integer(), nullable=True),
            sa.Column('downloaded_activities', sa.Integer(), nullable=True),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )

    if not _table_exists('user_achievements'):
        op.create_table('user_achievements',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('achievement_type', sa.String(50), nullable=False),
            sa.Column('achievement_name', sa.String(100), nullable=False),
            sa.Column('achievement_description', sa.Text(), nullable=True),
            sa.Column('grade_category', sa.String(20), nullable=True),
            sa.Column('metric_value', sa.Float(), nullable=True),
            sa.Column('earned_at', sa.DateTime(), nullable=False),
            sa.Column('notified', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('user_activity_residuals'):
        op.create_table('user_activity_residuals',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('activity_id', sa.String(50), nullable=False),
            sa.Column('activity_date', sa.DateTime(), nullable=False),
            sa.Column('total_distance_km', sa.Float(), nullable=True),
            sa.Column('total_elevation_gain_m', sa.Float(), nullable=True),
            sa.Column('activity_type', sa.String(50), nullable=True),
            sa.Column('segments', sa.JSON(), nullable=False),
            sa.Column('physics_model_version', sa.String(20), nullable=False),
            sa.Column('recency_weight', sa.Float(), nullable=True),
            sa.Column('excluded_from_training', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('user_learned_params'):
        op.create_table('user_learned_params',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('v_flat', sa.Float(), nullable=False),
            sa.Column('k_up', sa.Float(), nullable=True),
            sa.Column('k_tech', sa.Float(), nullable=True),
            sa.Column('a_param', sa.Float(), nullable=True),
            sa.Column('k_terrain_up', sa.Float(), nullable=True),
            sa.Column('k_terrain_down', sa.Float(), nullable=True),
            sa.Column('k_terrain_flat', sa.Float(), nullable=True),
            sa.Column('fatigue_alpha', sa.Float(), nullable=True),
            sa.Column('manually_adjusted', sa.Boolean(), nullable=True),
            sa.Column('n_activities_used', sa.Integer(), nullable=False),
            sa.Column('optimization_score', sa.Float(), nullable=True),
            sa.Column('param_uncertainties', sa.JSON(), nullable=True),
            sa.Column('pace_zone_overrides', sa.JSON(), nullable=True),
            sa.Column('last_trained', sa.DateTime(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )

    if not _table_exists('user_residual_models'):
        op.create_table('user_residual_models',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('model_blob', sa.LargeBinary(), nullable=False),
            sa.Column('n_activities_used', sa.Integer(), nullable=False),
            sa.Column('n_segments_trained', sa.Integer(), nullable=True),
            sa.Column('metrics', sa.JSON(), nullable=True),
            sa.Column('feature_importance', sa.JSON(), nullable=True),
            sa.Column('model_config', sa.JSON(), nullable=True),
            sa.Column('residual_variance', sa.Float(), nullable=True),
            sa.Column('last_trained', sa.DateTime(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )

    if not _table_exists('user_subscriptions'):
        op.create_table('user_subscriptions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('plan', sa.String(32), nullable=False),
            sa.Column('stripe_customer_id', sa.String(255), nullable=True),
            sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('canceled_at', sa.DateTime(), nullable=True),
            sa.Column('agent_messages_today', sa.Integer(), nullable=True),
            sa.Column('agent_messages_reset_date', sa.Date(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
        )

    # ── tables with FK → users + gpx_files ──
    if not _table_exists('training_plans'):
        op.create_table('training_plans',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('target_gpx_id', sa.Integer(), nullable=True),
            sa.Column('plan_name', sa.String(255), nullable=False),
            sa.Column('race_date', sa.DateTime(), nullable=True),
            sa.Column('race_description', sa.Text(), nullable=True),
            sa.Column('weeks', sa.JSON(), nullable=False),
            sa.Column('prediction_history', sa.JSON(), nullable=True),
            sa.Column('race_priority', sa.String(1), nullable=True),
            sa.Column('status', sa.String(32), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['target_gpx_id'], ['gpx_files.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # ── tables with FK → performance_snapshots ──
    if not _table_exists('grade_performance_history'):
        op.create_table('grade_performance_history',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('snapshot_id', sa.Integer(), nullable=True),
            sa.Column('grade_bucket', sa.Integer(), nullable=False),
            sa.Column('avg_pace', sa.Float(), nullable=False),
            sa.Column('sample_count', sa.Integer(), nullable=False),
            sa.Column('median_pace', sa.Float(), nullable=True),
            sa.Column('iqr_pace', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['snapshot_id'], ['performance_snapshots.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # ── tables with FK → gpx_files ──
    if not _table_exists('predictions'):
        op.create_table('predictions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('gpx_file_id', sa.Integer(), nullable=False),
            sa.Column('flat_pace', sa.Float(), nullable=False),
            sa.Column('user_fingerprint', sa.JSON(), nullable=True),
            sa.Column('anchor_ratios', sa.JSON(), nullable=True),
            sa.Column('total_time_seconds', sa.Float(), nullable=False),
            sa.Column('predicted_segments', sa.JSON(), nullable=False),
            sa.Column('annotations', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['gpx_file_id'], ['gpx_files.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # ── tables with FK → training_plans, strava_activities ──
    if not _table_exists('workout_completions'):
        op.create_table('workout_completions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('plan_id', sa.Integer(), nullable=False),
            sa.Column('week_number', sa.Integer(), nullable=False),
            sa.Column('day', sa.String(16), nullable=False),
            sa.Column('strava_activity_id', sa.Integer(), nullable=True),
            sa.Column('planned_distance_km', sa.Float(), nullable=True),
            sa.Column('actual_distance_km', sa.Float(), nullable=True),
            sa.Column('planned_workout_type', sa.String(32), nullable=True),
            sa.Column('planned_elevation_m', sa.Float(), nullable=True),
            sa.Column('actual_elevation_m', sa.Float(), nullable=True),
            sa.Column('compliance_score', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('matched_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['plan_id'], ['training_plans.id']),
            sa.ForeignKeyConstraint(['strava_activity_id'], ['strava_activities.id']),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('plan_id', 'week_number', 'day', name='uq_plan_week_day'),
        )

    if not _table_exists('notifications'):
        op.create_table('notifications',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('type', sa.String(32), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('read', sa.Boolean(), default=False, nullable=False),
            sa.Column('plan_id', sa.Integer(), sa.ForeignKey('training_plans.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if not _table_exists('race_results'):
        op.create_table('race_results',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('plan_id', sa.Integer(), nullable=False),
            sa.Column('strava_activity_id', sa.Integer(), nullable=False),
            sa.Column('prediction_id', sa.Integer(), nullable=True),
            sa.Column('actual_total_seconds', sa.Float(), nullable=False),
            sa.Column('predicted_total_seconds', sa.Float(), nullable=True),
            sa.Column('difference_seconds', sa.Float(), nullable=True),
            sa.Column('split_comparison', sa.JSON(), nullable=True),
            sa.Column('insights', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['plan_id'], ['training_plans.id']),
            sa.ForeignKeyConstraint(['strava_activity_id'], ['strava_activities.id']),
            sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('plan_id'),
        )

    if not _table_exists('training_routes'):
        op.create_table('training_routes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('source', sa.String(32), nullable=False),
            sa.Column('route_data', sa.JSON(), nullable=False),
            sa.Column('distance_km', sa.Float(), nullable=False),
            sa.Column('elevation_gain_m', sa.Float(), nullable=False),
            sa.Column('elevation_loss_m', sa.Float(), nullable=False),
            sa.Column('center_lat', sa.Float(), nullable=True),
            sa.Column('center_lon', sa.Float(), nullable=True),
            sa.Column('segments', sa.JSON(), nullable=True),
            sa.Column('terrain_summary', sa.JSON(), nullable=True),
            sa.Column('tags', sa.JSON(), nullable=True),
            sa.Column('generation_params', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # ── cache tables (no FKs) ──
    if not _table_exists('weather_cache'):
        op.create_table('weather_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('cache_key', sa.String(128), nullable=False),
            sa.Column('data', sa.JSON(), nullable=False),
            sa.Column('cache_type', sa.String(16), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _table_exists('terrain_cache'):
        op.create_table('terrain_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('cache_key', sa.String(128), nullable=False),
            sa.Column('data', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    # ── indexes (all guarded) ──
    if not _index_exists('user_activity_residuals', 'idx_user_date'):
        op.create_index('idx_user_date', 'user_activity_residuals',
                        ['user_id', 'activity_date'])
    if not _index_exists('user_activity_residuals', 'idx_user_version'):
        op.create_index('idx_user_version', 'user_activity_residuals',
                        ['user_id', 'physics_model_version'])
    if not _index_exists('user_activity_residuals', 'ix_user_activity_residuals_activity_date'):
        op.create_index('ix_user_activity_residuals_activity_date',
                        'user_activity_residuals', ['activity_date'])
    if not _index_exists('user_activity_residuals', 'ix_user_activity_residuals_activity_id'):
        op.create_index('ix_user_activity_residuals_activity_id',
                        'user_activity_residuals', ['activity_id'])
    if not _index_exists('user_activity_residuals', 'ix_user_activity_residuals_user_id'):
        op.create_index('ix_user_activity_residuals_user_id',
                        'user_activity_residuals', ['user_id'])

    if not _index_exists('weather_cache', 'ix_weather_cache_cache_key'):
        op.create_index('ix_weather_cache_cache_key', 'weather_cache',
                        ['cache_key'], unique=True)
    if not _index_exists('terrain_cache', 'ix_terrain_cache_cache_key'):
        op.create_index('ix_terrain_cache_cache_key', 'terrain_cache',
                        ['cache_key'], unique=True)

    if not _index_exists('notifications', 'ix_notifications_user_id'):
        op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    if not _index_exists('notifications', 'ix_notification_user_read'):
        op.create_index('ix_notification_user_read', 'notifications',
                        ['user_id', 'read', 'created_at'])

    if not _index_exists('performance_snapshots', 'ix_perf_snapshot_user_period'):
        op.create_index('ix_perf_snapshot_user_period', 'performance_snapshots',
                        ['user_id', 'period_type', 'snapshot_date'])
    if not _index_exists('predictions', 'ix_prediction_user_date'):
        op.create_index('ix_prediction_user_date', 'predictions',
                        ['user_id', 'created_at'])
    if not _index_exists('strava_activities', 'ix_strava_activity_user_date'):
        op.create_index('ix_strava_activity_user_date', 'strava_activities',
                        ['user_id', 'start_date'])

    if not _index_exists('training_routes', 'ix_training_route_user'):
        op.create_index('ix_training_route_user', 'training_routes', ['user_id'])
    if not _index_exists('training_routes', 'ix_training_route_center'):
        op.create_index('ix_training_route_center', 'training_routes',
                        ['center_lat', 'center_lon'])


def downgrade():
    op.drop_table('race_results')
    op.drop_table('workout_completions')
    op.drop_table('notifications')
    op.drop_table('predictions')
    op.drop_table('grade_performance_history')
    op.drop_table('training_plans')
    op.drop_table('training_routes')
    op.drop_table('terrain_cache')
    op.drop_table('weather_cache')
    op.drop_table('user_subscriptions')
    op.drop_table('user_residual_models')
    op.drop_table('user_learned_params')
    op.drop_table('user_activity_residuals')
    op.drop_table('user_achievements')
    op.drop_table('sync_status')
    op.drop_table('strava_activity_cache')
    op.drop_table('strava_activities')
    op.drop_table('performance_snapshots')
    op.drop_table('gpx_files')
    op.drop_table('evaluation_status')
    op.drop_table('agent_param_snapshots')
    op.drop_table('users')

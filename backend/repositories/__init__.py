"""Repository layer for database access abstraction."""

from .base import BaseRepository
from .user_repository import UserRepository
from .gpx_file_repository import GPXFileRepository
from .prediction_repository import PredictionRepository
from .activity_repository import ActivityRepository
from .strava_cache_repository import StravaCacheRepository
from .sync_status_repository import SyncStatusRepository
from .user_learned_params_repository import UserLearnedParamsRepository
from .user_residual_model_repository import UserResidualModelRepository
from .user_activity_residual_repository import UserActivityResidualRepository
from .performance_repository import PerformanceRepository
from .achievement_repository import AchievementRepository
from .subscription_repository import SubscriptionRepository
from .training_plan_repository import TrainingPlanRepository
from .notification_repository import NotificationRepository
from .agent_snapshot_repository import AgentSnapshotRepository
from .evaluation_status_repository import EvaluationStatusRepository
from .terrain_cache_repository import TerrainCacheRepository
from .route_cache_repository import RouteCacheRepository
from .weather_cache_repository import WeatherCacheRepository
from .race_result_repository import RaceResultRepository
from .training_route_repository import TrainingRouteRepository
from .training_location_repository import TrainingLocationRepository
from .user_training_preferences_repository import UserTrainingPreferencesRepository
from .agent_conversation_repository import AgentConversationRepository
from .waitlist_repository import WaitlistRepository
from .race_repository import RaceRepository
from .daily_checkin_repository import DailyCheckinRepository
from .plan_adjustment_repository import PlanAdjustmentRepository
from .user_connection_repository import UserConnectionRepository

__all__ = [
    'BaseRepository',
    'UserRepository',
    'GPXFileRepository',
    'PredictionRepository',
    'ActivityRepository',
    'StravaCacheRepository',
    'SyncStatusRepository',
    'UserLearnedParamsRepository',
    'UserResidualModelRepository',
    'UserActivityResidualRepository',
    'PerformanceRepository',
    'AchievementRepository',
    'SubscriptionRepository',
    'TrainingPlanRepository',
    'NotificationRepository',
    'AgentSnapshotRepository',
    'EvaluationStatusRepository',
    'TerrainCacheRepository',
    'RouteCacheRepository',
    'WeatherCacheRepository',
    'RaceResultRepository',
    'TrainingRouteRepository',
    'TrainingLocationRepository',
    'UserTrainingPreferencesRepository',
    'AgentConversationRepository',
    'WaitlistRepository',
    'RaceRepository',
    'DailyCheckinRepository',
    'PlanAdjustmentRepository',
    'UserConnectionRepository',
]

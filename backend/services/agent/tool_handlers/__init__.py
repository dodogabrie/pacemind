"""Tool execution handlers for the LLM prediction agent.

Each handler maps a tool name to a function that executes against
existing services and returns a result dict.
"""

from typing import Dict, Any

from config.hybrid_config import get_logger
from repositories import UserLearnedParamsRepository

from services.agent.tool_handlers.params import (
    _handle_get_current_params,
    _handle_adjust_params,
    _handle_rollback_params,
)
from services.agent.tool_handlers.prediction import (
    _handle_get_tier_status,
    _handle_run_prediction,
    _handle_compare_predictions,
    _handle_retrain_model,
)
from services.agent.tool_handlers.routes import (
    _handle_list_gpx_routes,
    _handle_get_route_gpx_link,
    _handle_get_route_segments,
    _handle_get_terrain_analysis,
    _handle_get_weather_conditions,
    _handle_search_training_routes,
    _handle_generate_training_route,
    _handle_list_training_locations,
    _handle_set_training_location_for_day,
    _handle_build_route_workout,
)
from services.agent.tool_handlers.training import (
    _handle_get_training_history,
    _handle_get_performance_trends,
    _handle_get_training_load,
    _handle_generate_training_week,
    _handle_generate_full_plan,
    _handle_save_training_plan,
    _handle_get_plan_compliance,
    _handle_inspect_training_plan,
    _handle_adjust_training_week,
    _handle_get_plan_templates,
    _handle_get_season_overview,
    _handle_get_training_preferences,
    _handle_save_training_preferences,
    _handle_raise_long_run_cap,
    _handle_search_tuneup_races,
    _handle_start_onboarding_questionnaire,
    _handle_preview_capacity,
    _handle_infer_terrain_profile,
    _handle_match_routes_to_plan,
)
from services.agent.tool_handlers.race import (
    _handle_get_race_profile,
    _handle_get_race_briefing,
    _handle_get_pacing_strategy,
    _handle_get_past_performance,
    _handle_generate_race_report,
    _handle_get_race_report,
    _handle_find_race_online,
)
from services.agent.tool_handlers.activities import (
    _handle_list_activities,
    _handle_get_activity_detail,
    _handle_compare_to_plan,
    _handle_get_segment_improvement,
)
from services.agent.tool_handlers.nutrition import (
    _handle_get_nutrition_estimate,
)
from services.agent.tool_handlers.equipment import (
    _handle_get_equipment_suggestion,
)
from services.agent.tool_handlers.knowledge import (
    _handle_lookup_coaching_knowledge,
    _handle_assess_training_readiness,
)
from services.agent.tool_handlers.annotations import (
    _handle_suggest_waypoints,
    _handle_manage_annotations,
)
from services.agent.tool_handlers.validation import (
    _assess_week_quality,
    _validate_single_week,
    _assess_edit_impact,
)

logger = get_logger(__name__)


def handle_tool_call(tool_name: str, tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Dispatch a tool call to the appropriate handler.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Tool input parameters
        user_id: Authenticated user ID

    Returns:
        Result dict to feed back to Claude
    """
    handlers = {
        'get_current_params': _handle_get_current_params,
        'adjust_params': _handle_adjust_params,
        'get_tier_status': _handle_get_tier_status,
        'run_prediction': _handle_run_prediction,
        'compare_predictions': _handle_compare_predictions,
        'retrain_model': _handle_retrain_model,
        'rollback_params': _handle_rollback_params,
        'list_gpx_routes': _handle_list_gpx_routes,
        'get_route_gpx_link': _handle_get_route_gpx_link,
        'get_terrain_analysis': _handle_get_terrain_analysis,
        'get_weather_conditions': _handle_get_weather_conditions,
        'get_training_load': _handle_get_training_load,
        'get_race_briefing': _handle_get_race_briefing,
        'get_pacing_strategy': _handle_get_pacing_strategy,
        'get_past_performance': _handle_get_past_performance,
        'get_nutrition_estimate': _handle_get_nutrition_estimate,
        'suggest_waypoints': _handle_suggest_waypoints,
        'manage_annotations': _handle_manage_annotations,
        'get_route_segments': _handle_get_route_segments,
        'get_training_history': _handle_get_training_history,
        'get_performance_trends': _handle_get_performance_trends,
        'get_race_profile': _handle_get_race_profile,
        'generate_training_week': _handle_generate_training_week,
        'generate_full_plan': _handle_generate_full_plan,
        'save_training_plan': _handle_save_training_plan,
        'get_equipment_suggestion': _handle_get_equipment_suggestion,
        'get_plan_compliance': _handle_get_plan_compliance,
        'inspect_training_plan': _handle_inspect_training_plan,
        'adjust_training_week': _handle_adjust_training_week,
        'get_plan_templates': _handle_get_plan_templates,
        'get_season_overview': _handle_get_season_overview,
        'generate_race_report': _handle_generate_race_report,
        'get_race_report': _handle_get_race_report,
        'search_training_routes': _handle_search_training_routes,
        'generate_training_route': _handle_generate_training_route,
        'list_training_locations': _handle_list_training_locations,
        'set_training_location_for_day': _handle_set_training_location_for_day,
        'build_route_workout': _handle_build_route_workout,
        'lookup_coaching_knowledge': _handle_lookup_coaching_knowledge,
        'assess_training_readiness': _handle_assess_training_readiness,
        'get_training_preferences': _handle_get_training_preferences,
        'save_training_preferences': _handle_save_training_preferences,
        'raise_long_run_cap': _handle_raise_long_run_cap,
        'search_tuneup_races': _handle_search_tuneup_races,
        'find_race_online': _handle_find_race_online,
        'start_onboarding_questionnaire': _handle_start_onboarding_questionnaire,
        'preview_capacity': _handle_preview_capacity,
        'infer_terrain_profile': _handle_infer_terrain_profile,
        'match_routes_to_plan': _handle_match_routes_to_plan,
        'list_activities': _handle_list_activities,
        'get_activity_detail': _handle_get_activity_detail,
        'compare_to_plan': _handle_compare_to_plan,
        'get_segment_improvement': _handle_get_segment_improvement,
    }

    handler = handlers.get(tool_name)
    if not handler:
        return {'error': f'Unknown tool: {tool_name}'}

    try:
        return handler(tool_input, user_id)
    except Exception as e:
        logger.exception(f"Tool '{tool_name}' failed: {e}")
        from repositories import UserLearnedParamsRepository
        UserLearnedParamsRepository().rollback()
        return {'error': f'Tool execution failed: {str(e)}'}

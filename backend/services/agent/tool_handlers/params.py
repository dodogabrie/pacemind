"""Parameter management handlers: get, adjust, rollback."""

from typing import Dict, Any

from config.hybrid_config import get_logger, DEFAULT_PARAMS
from models import UserLearnedParams
from models.agent_param_snapshot import AgentParamSnapshot
from repositories import UserLearnedParamsRepository, AgentSnapshotRepository
from services.parameter_learning_service import ParameterLearningService
from services.agent.safety import validate_adjustments, get_param_info

logger = get_logger(__name__)


def _handle_get_current_params(tool_input: Dict, user_id: int) -> Dict:
    """Get user's current physics parameters."""
    service = ParameterLearningService()
    learned = service.get_user_params(user_id)

    if learned:
        source = 'learned'
        params = learned
    else:
        source = 'defaults'
        params = DEFAULT_PARAMS.copy()

    # Check if manually adjusted
    learned_params_repo = UserLearnedParamsRepository()
    record = learned_params_repo.get_for_user(user_id)
    manually_adjusted = getattr(record, 'manually_adjusted', False) if record else False

    return {
        'params': params,
        'source': source,
        'manually_adjusted': manually_adjusted,
        'param_info': get_param_info(),
    }


def _handle_adjust_params(tool_input: Dict, user_id: int) -> Dict:
    """Adjust physics parameters with safety validation."""
    adjustments = tool_input.get('adjustments', {})
    reason = tool_input.get('reason', 'Agent adjustment')

    if not adjustments:
        return {'error': 'No adjustments provided'}

    # Get current params
    service = ParameterLearningService()
    current_params = service.get_or_default_params(user_id)

    # Validate adjustments
    validated, messages = validate_adjustments(adjustments, current_params)

    if not validated:
        return {'error': 'No valid adjustments', 'messages': messages}

    # Create snapshot before modifying
    AgentParamSnapshot.create_snapshot(
        user_id=user_id,
        params=current_params,
        action='adjust_params',
        description=reason
    )

    # Apply changes
    learned_params_repo = UserLearnedParamsRepository()
    record = learned_params_repo.get_for_user(user_id)

    if record:
        for param_name, value in validated.items():
            setattr(record, param_name, value)
        record.manually_adjusted = True
    else:
        # Create new record with defaults + adjustments
        new_params = DEFAULT_PARAMS.copy()
        new_params.update(validated)
        record = UserLearnedParams(
            user_id=user_id,
            v_flat=new_params['v_flat'],
            k_up=new_params['k_up'],
            k_tech=new_params['k_tech'],
            a_param=new_params['a_param'],
            k_terrain_up=new_params['k_terrain_up'],
            k_terrain_down=new_params['k_terrain_down'],
            k_terrain_flat=new_params['k_terrain_flat'],
            fatigue_alpha=new_params['fatigue_alpha'],
            n_activities_used=0,
            optimization_score=None,
            manually_adjusted=True,
        )
        learned_params_repo.create(record)

    learned_params_repo.commit()

    # Read back final state
    new_params = record.to_dict()

    return {
        'previous_params': current_params,
        'new_params': new_params,
        'changes_applied': validated,
        'messages': messages,
    }


def _handle_rollback_params(tool_input: Dict, user_id: int) -> Dict:
    """Rollback to the most recent parameter snapshot."""
    snapshot = AgentParamSnapshot.get_latest(user_id)

    if not snapshot:
        return {'error': 'No snapshots available to rollback to'}

    restored_params = snapshot.params_snapshot

    # Apply restored params
    learned_params_repo = UserLearnedParamsRepository()
    snapshot_repo = AgentSnapshotRepository()
    record = learned_params_repo.get_for_user(user_id)

    if record:
        for param_name, value in restored_params.items():
            if hasattr(record, param_name):
                setattr(record, param_name, value)
        record.manually_adjusted = False
    else:
        record = UserLearnedParams(
            user_id=user_id,
            v_flat=restored_params.get('v_flat', DEFAULT_PARAMS['v_flat']),
            k_up=restored_params.get('k_up', DEFAULT_PARAMS['k_up']),
            k_tech=restored_params.get('k_tech', DEFAULT_PARAMS['k_tech']),
            a_param=restored_params.get('a_param', DEFAULT_PARAMS['a_param']),
            k_terrain_up=restored_params.get('k_terrain_up', DEFAULT_PARAMS['k_terrain_up']),
            k_terrain_down=restored_params.get('k_terrain_down', DEFAULT_PARAMS['k_terrain_down']),
            k_terrain_flat=restored_params.get('k_terrain_flat', DEFAULT_PARAMS['k_terrain_flat']),
            fatigue_alpha=restored_params.get('fatigue_alpha', DEFAULT_PARAMS['fatigue_alpha']),
            n_activities_used=0,
            manually_adjusted=False,
        )
        learned_params_repo.create(record)

    # Delete the used snapshot
    snapshot_repo.delete(snapshot)
    learned_params_repo.commit()

    return {
        'restored_params': restored_params,
        'snapshot_action': snapshot.action,
        'snapshot_description': snapshot.description,
        'snapshot_date': snapshot.created_at.isoformat(),
    }

"""Training plan handlers: history, trends, load, generate, save, compliance, etc."""

from typing import Dict, Any
from datetime import datetime, timedelta, timezone

from config.hybrid_config import get_logger
from models import Activity, PerformanceSnapshot
from repositories import GPXFileRepository, TrainingPlanRepository
from services.training_load_service import TrainingLoadService
from services.agent.tool_handlers.validation import (
    _get_gpx_points, _is_recovery_week, _validate_single_week,
    _inject_calendar_dates, _assess_week_quality, _assess_edit_impact,
    _assess_coaching_knowledge_warnings, _assess_timeline_reasonableness,
    _compute_gpx_elevation_gain,
    _DAY_NAMES, VALID_WORKOUT_TYPES,
)

logger = get_logger(__name__)

# Per-user cache of validated weeks from generate_training_week calls
_session_validated_weeks: Dict[int, list] = {}

# Per-user cache of race targets (set on first week call, reused on subsequent calls)
_session_race_targets: Dict[int, Dict] = {}

# Per-user cache of feasibility warnings produced by generate_full_plan,
# persisted into TrainingPlan.warnings on save.
_session_plan_warnings: Dict[int, list] = {}


def _cache_validated_week(user_id: int, week: Dict):
    """Cache a validated week, replacing any existing week with the same number."""
    if user_id not in _session_validated_weeks:
        _session_validated_weeks[user_id] = []
    wn = week['week_number']
    _session_validated_weeks[user_id] = [
        w for w in _session_validated_weeks[user_id] if w['week_number'] != wn
    ]
    _session_validated_weeks[user_id].append(week)
    _session_validated_weeks[user_id].sort(key=lambda w: w['week_number'])


def _handle_get_training_history(tool_input: Dict, user_id: int) -> Dict:
    """Get weekly training aggregates from Strava activities."""
    from sqlalchemy import func, extract
    weeks = tool_input.get('weeks', 8)
    weeks = min(max(weeks, 1), 52)

    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)

    activities = (
        Activity.query
        .filter(Activity.user_id == user_id)
        .filter(Activity.start_date >= cutoff)
        .order_by(Activity.start_date.asc())
        .all()
    )

    if not activities:
        return {'error': 'No activities found in the requested period', 'weeks_requested': weeks}

    # Group by ISO week
    from collections import defaultdict
    weekly = defaultdict(list)
    for act in activities:
        iso_year, iso_week, _ = act.start_date.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        weekly[key].append(act)

    week_summaries = []
    for week_key in sorted(weekly.keys()):
        acts = weekly[week_key]
        distances = [a.distance / 1000 for a in acts]  # m -> km
        total_km = sum(distances)
        longest = max(distances) if distances else 0

        week_summaries.append({
            'week': week_key,
            'activity_count': len(acts),
            'volume_km': round(total_km, 1),
            'elevation_gain_m': round(sum(a.elevation_gain_m or 0 for a in acts)),
            'longest_run_km': round(longest, 1),
            'start_date': acts[0].start_date.strftime('%Y-%m-%d'),
        })

    return {
        'weeks': week_summaries,
        'total_weeks': len(week_summaries),
        'total_activities': len(activities),
    }


def _handle_get_performance_trends(tool_input: Dict, user_id: int) -> Dict:
    """Get performance trend data from snapshots."""
    period_type = tool_input.get('period_type', 'weekly')
    limit = tool_input.get('limit', 12)
    limit = min(max(limit, 1), 52)

    snapshots = (
        PerformanceSnapshot.query
        .filter_by(user_id=user_id, period_type=period_type)
        .order_by(PerformanceSnapshot.snapshot_date.desc())
        .limit(limit)
        .all()
    )

    if not snapshots:
        return {'error': f'No {period_type} performance snapshots found'}

    # Reverse to chronological order
    snapshots = list(reversed(snapshots))

    trends = []
    for snap in snapshots:
        trends.append({
            'period_start': snap.period_start.strftime('%Y-%m-%d'),
            'period_end': snap.period_end.strftime('%Y-%m-%d'),
            'flat_pace': round(snap.flat_pace, 2),
            'activity_count': snap.activity_count,
            'total_distance_km': round(snap.total_distance_km, 1) if snap.total_distance_km else None,
            'total_elevation_m': round(snap.total_elevation_m, 0) if snap.total_elevation_m else None,
        })

    # Compute trend direction
    if len(trends) >= 2:
        first_pace = trends[0]['flat_pace']
        last_pace = trends[-1]['flat_pace']
        pace_change = last_pace - first_pace
        if abs(pace_change) < 0.05:
            pace_trend = 'stable'
        elif pace_change < 0:
            pace_trend = 'improving'  # lower pace = faster
        else:
            pace_trend = 'declining'
    else:
        pace_trend = 'insufficient_data'

    return {
        'trends': trends,
        'period_type': period_type,
        'pace_trend': pace_trend,
        'total_periods': len(trends),
    }


def _handle_get_training_load(tool_input: Dict, user_id: int) -> Dict:
    """Get user's current training load metrics."""
    service = TrainingLoadService()
    return service.get_training_load(user_id)


def _handle_generate_training_week(tool_input: Dict, user_id: int) -> Dict:
    """Validate and structure training weeks — supports batch and single mode."""
    batch_weeks = tool_input.get('weeks')

    # Parse race_date / total_weeks for calendar date injection
    race_date_str = tool_input.get('race_date')
    total_weeks_param = tool_input.get('total_weeks')
    race_date = None
    if race_date_str:
        try:
            race_date = datetime.strptime(race_date_str, '%Y-%m-%d')
        except ValueError:
            pass

    # --- Timeline reasonableness check (runs before week validation) ---
    target_gpx_id = tool_input.get('target_gpx_id')
    target_race_distance_km = tool_input.get('target_race_distance_km')
    timeline_warnings: list[str] = []
    plan_total_weeks = total_weeks_param or (len(batch_weeks) if batch_weeks else 0)
    if plan_total_weeks > 0:
        timeline_warnings = _assess_timeline_reasonableness(
            total_weeks=plan_total_weeks,
            target_distance_km=target_race_distance_km,
            target_gpx_id=target_gpx_id,
            user_id=user_id,
        )

    if batch_weeks:
        results = []
        all_valid = True
        for week_input in batch_weeks:
            result = _validate_single_week(week_input)
            results.append(result)
            if 'error' in result:
                all_valid = False
            else:
                _cache_validated_week(user_id, result)

        # Inject calendar dates if race_date provided
        valid_weeks = [r for r in results if r.get('valid')]
        if race_date and valid_weeks:
            _inject_calendar_dates(valid_weeks, race_date)

        valid_count = len(valid_weeks)

        # Aggregate quality warnings across all weeks
        all_quality_warnings = list(timeline_warnings)
        for r in results:
            if r.get('quality_warnings'):
                all_quality_warnings.extend(r['quality_warnings'])

        # Cross-week coaching knowledge validation
        coaching_warnings = _assess_coaching_knowledge_warnings(
            valid_weeks, user_id, target_gpx_id=target_gpx_id
        )
        all_quality_warnings.extend(coaching_warnings)

        response = {
            'weeks': results,
            'total_validated': valid_count,
            'total_submitted': len(batch_weeks),
            'all_valid': all_valid,
            'valid': all_valid,
        }
        if all_quality_warnings:
            response['quality_warnings'] = all_quality_warnings
        if race_date:
            response['race_day_of_week'] = _DAY_NAMES.get(race_date.weekday(), 'Unknown')
        return response

    # Resolve race distance/elevation — cache on first call, reuse on subsequent
    cached_targets = _session_race_targets.get(user_id, {})
    race_dist_km = target_race_distance_km or cached_targets.get('distance_km', 0)
    race_elev_m = cached_targets.get('elevation_m', 0)

    if target_gpx_id and not race_elev_m:
        try:
            gpx_repo = GPXFileRepository()
            gpx_file = gpx_repo.get_user_file(target_gpx_id, user_id)
            if gpx_file and gpx_file.data:
                race_dist_km = gpx_file.data.get('total_distance_km') or race_dist_km
                points = gpx_file.data.get('points', [])
                if points:
                    race_elev_m = _compute_gpx_elevation_gain(points)
        except Exception as e:
            logger.warning(f"generate_training_week: could not load race targets from GPX {target_gpx_id}: {e}")

    # Cache for subsequent calls in this session
    if race_dist_km > 0:
        _session_race_targets[user_id] = {
            'distance_km': race_dist_km,
            'elevation_m': race_elev_m,
        }

    # Single-week mode
    result = _validate_single_week(
        tool_input,
        race_distance_km=race_dist_km,
        race_elevation_m=race_elev_m,
    )
    if result.get('valid'):
        _cache_validated_week(user_id, result)
        if race_date and total_weeks_param:
            _inject_calendar_dates([result], race_date)

    # Prepend timeline warnings (single-week mode)
    if timeline_warnings and result.get('valid'):
        existing = result.get('quality_warnings') or []
        result['quality_warnings'] = timeline_warnings + existing

    # Apply coaching knowledge validation using session cache for context
    if result.get('valid'):
        cached = _session_validated_weeks.get(user_id, [])
        if cached:
            coaching_warnings = _assess_coaching_knowledge_warnings(
                cached, user_id, target_gpx_id=target_gpx_id
            )
            if coaching_warnings:
                existing = result.get('quality_warnings') or []
                result['quality_warnings'] = existing + coaching_warnings

    response = dict(result)
    if race_date:
        response['race_day_of_week'] = _DAY_NAMES.get(race_date.weekday(), 'Unknown')

    # Include summary of all weeks generated so far so the LLM can plan progressively
    cached = _session_validated_weeks.get(user_id, [])
    if cached:
        plan_so_far = []
        for w in cached:
            plan_so_far.append({
                'week_number': w.get('week_number'),
                'theme': w.get('theme'),
                'total_km': w.get('total_km'),
                'total_elevation_m': w.get('total_elevation_m'),
            })
        response['plan_so_far'] = plan_so_far
        response['weeks_generated'] = len(cached)

    # Include weeks remaining and pre-computed targets
    if total_weeks_param:
        response['total_weeks_in_plan'] = total_weeks_param
        response['weeks_remaining'] = total_weeks_param - len(cached)

    # Pre-compute race targets from target_gpx or stated distance
    race_dist_km = target_race_distance_km or 0
    race_elev_m = 0
    if target_gpx_id:
        try:
            gpx_repo = GPXFileRepository()
            gpx_file = gpx_repo.get_user_file(target_gpx_id, user_id)
            if gpx_file and gpx_file.data:
                race_dist_km = gpx_file.data.get('total_distance_km') or race_dist_km
                points = gpx_file.data.get('points', [])
                if points:
                    race_elev_m = _compute_gpx_elevation_gain(points)
        except Exception as e:
            logger.warning(f"generate_training_week: could not load race targets from GPX {target_gpx_id}: {e}")

    if race_dist_km > 0:
        response['race_targets'] = {
            'race_distance_km': round(race_dist_km, 1),
            'race_elevation_m': round(race_elev_m) if race_elev_m else None,
            'race_ratio_m_per_km': round(race_elev_m / race_dist_km) if race_elev_m and race_dist_km else None,
            'peak_long_run_km': round(race_dist_km * 0.75, 1),
            'peak_long_run_elev_m': round(race_dist_km * 0.75 * race_elev_m / race_dist_km) if race_elev_m else None,
            'peak_weekly_elev_target_m': round(race_elev_m) if race_elev_m else None,
        }

    return response


def _handle_save_training_plan(tool_input: Dict, user_id: int) -> Dict:
    """Save a complete training plan to the database."""
    from models.training_plan import TrainingPlan

    plan_name = tool_input.get('plan_name', 'Training Plan')
    race_date_str = tool_input.get('race_date')
    target_gpx_id = tool_input.get('target_gpx_id')
    race_description = tool_input.get('race_description')
    weeks = tool_input.get('weeks', [])

    # Auto-collect from session cache if weeks not provided
    if not weeks and user_id in _session_validated_weeks:
        weeks = _session_validated_weeks[user_id]
        logger.info(f"Auto-collected {len(weeks)} cached weeks for user {user_id}")

    if not weeks:
        return {'error': 'At least one week is required. Generate weeks first with generate_training_week.'}

    race_date = None
    if race_date_str:
        try:
            race_date = datetime.strptime(race_date_str, '%Y-%m-%d')
        except ValueError:
            return {'error': f'Invalid race_date format: {race_date_str}'}

    # Verify target GPX belongs to user if provided
    gpx_repo = GPXFileRepository()
    plan_repo = TrainingPlanRepository()
    if target_gpx_id:
        gpx = gpx_repo.get_user_file(target_gpx_id, user_id)
        if not gpx:
            return {'error': f'GPX route {target_gpx_id} not found'}

    # Inject calendar dates as safety net if race_date is set
    if race_date and weeks:
        _inject_calendar_dates(weeks, race_date)

    race_priority = tool_input.get('race_priority')
    if race_priority and race_priority not in ('A', 'B', 'C'):
        race_priority = None

    plan_warnings = _session_plan_warnings.get(user_id) or []
    plan = TrainingPlan(
        user_id=user_id,
        target_gpx_id=target_gpx_id,
        plan_name=plan_name,
        race_date=race_date,
        race_description=race_description,
        race_priority=race_priority,
        weeks=weeks,
        warnings=plan_warnings,
        status='draft',
    )
    plan_repo.create(plan)
    plan_repo.commit()

    # Clear session cache after successful save
    _session_validated_weeks.pop(user_id, None)
    _session_race_targets.pop(user_id, None)
    _session_plan_warnings.pop(user_id, None)

    return {
        'plan_id': plan.id,
        'plan_name': plan.plan_name,
        'status': 'saved',
        'weeks_count': len(weeks),
    }


def _handle_generate_full_plan(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Generate a complete training plan using the constraint-based engine.

    Pipeline:
      1. Load saved prefs.
      2. If REQUIRED_PREFS_FIELDS missing → return requires_onboarding=True.
      3. Otherwise call plan_orchestrator → engine + route binding + feasibility.
      4. Fallback: if no prefs are saved, fall back to the legacy engine path
         (back-compat) but still return a warnings array.
    """
    from services.plan_engine import (
        generate_plan, MissingPreferencesError, REQUIRED_PREFS_FIELDS,
        validate_plan_feasibility,
    )
    from repositories import UserTrainingPreferencesRepository

    # Resolve key_sections from GPX if provided
    key_sections = None
    target_gpx_id = tool_input.get('target_gpx_id')
    race_type = tool_input.get('race_type', 'loop')
    training_ratio = None

    if target_gpx_id:
        try:
            from services.agent.tool_handlers.race import _handle_get_race_profile
            profile = _handle_get_race_profile({'gpx_id': target_gpx_id}, user_id)
            if 'key_sections' in profile:
                key_sections = profile['key_sections']
            if 'race_type' in profile:
                race_type = profile['race_type']
            if 'elevation_ratio_m_per_km' in profile:
                training_ratio = profile['elevation_ratio_m_per_km']
        except Exception as e:
            logger.warning(f"Could not get race profile for GPX {target_gpx_id}: {e}")

    prefs_obj = UserTrainingPreferencesRepository().get_by_user(user_id)
    prefs_dict = prefs_obj.to_dict() if prefs_obj else None

    # If the agent provided some prefs inline (mountain_days, strength), merge them
    # so an in-flight call can complete without requiring a save first.
    if tool_input.get('mountain_days') is not None:
        prefs_dict = dict(prefs_dict or {})
        prefs_dict['mountain_days'] = tool_input['mountain_days']
    for key in ('treadmill_days', 'treadmill_max_incline_pct',
                'intensity_distribution', 'long_long_run_hours', 'long_long_run_every_weeks',
                'max_long_run_hours'):
        if tool_input.get(key) is not None:
            prefs_dict = dict(prefs_dict or {})
            prefs_dict[key] = tool_input[key]

    # Gate: required prefs.
    missing = [f for f in REQUIRED_PREFS_FIELDS
               if not prefs_dict or prefs_dict.get(f) in (None, '', [])]
    if missing:
        return {
            'requires_onboarding': True,
            'missing_fields': missing,
            'note': (
                'Required preferences are missing. Call '
                'start_onboarding_questionnaire to surface the wizard, or ask '
                'the user inline using the schema it returns.'
            ),
        }

    # Gate: athlete readiness. Refuse plans that are too aggressive for
    # the athlete's current capacity (long-run baseline, CTL, available
    # weeks). The agent can override by passing force_unrealistic=True
    # after explaining the risks to the user.
    if not tool_input.get('force_unrealistic'):
        from services.plan_readiness import (
            assess_readiness, get_athlete_baseline, suggest_alternative_races,
        )
        baseline = get_athlete_baseline(user_id)
        athlete_lr = (tool_input.get('athlete_longest_run_km')
                      or baseline.get('longest_run_km')
                      or (prefs_dict or {}).get('max_long_run_km')
                      or 0.0)
        athlete_wk = (tool_input.get('athlete_weekly_km')
                      or baseline.get('weekly_km') or 0.0)
        verdict = assess_readiness(
            race_distance_km=tool_input.get('race_distance_km') or 0,
            available_weeks=tool_input.get('total_weeks') or 0,
            athlete_longest_run_km=float(athlete_lr),
            athlete_weekly_km=float(athlete_wk),
            ctl=baseline.get('ctl'),
        )
        if verdict.status == 'unrealistic':
            alternatives = suggest_alternative_races(
                race_distance_km=tool_input.get('race_distance_km') or 0,
                athlete_longest_run_km=float(athlete_lr),
            )
            return {
                'requires_user_decision': True,
                'conflict': 'race_not_feasible',
                'verdict': verdict.to_dict(),
                'baseline': baseline,
                'alternatives': alternatives,
                'note': (
                    "The athlete's current capacity does not safely support "
                    "this race in the requested window. Do NOT regenerate "
                    "silently. Explain the verdict to the user, present the "
                    "alternative races (or recommend extending the window), "
                    "and only retry with force_unrealistic=true after the "
                    "user explicitly accepts the injury risk."
                ),
            }

    # Gate: long-run cap below race-derived target.
    # Mirrors plan_engine.compute_weekly_targets:416-420 so we can negotiate
    # with the user before the engine silently clips every week to the cap.
    if not tool_input.get('acknowledge_long_run_cap'):
        max_lr_cap = (prefs_dict or {}).get('max_long_run_km')
        race_distance_km = tool_input.get('race_distance_km') or 0
        if max_lr_cap and race_distance_km > 0:
            from services.plan_engine import (
                LONG_RUN_PEAK_FRACTION, LONG_RUN_MAX_FRACTION,
            )
            overrides = tool_input.get('overrides') or {}
            peak_frac = overrides.get('long_run_peak_fraction', LONG_RUN_PEAK_FRACTION)
            target_long_run = min(race_distance_km * peak_frac,
                                  race_distance_km * LONG_RUN_MAX_FRACTION)
            if target_long_run - max_lr_cap > 5:
                race_elev = tool_input.get('race_elevation_m') or 0
                race_ratio = race_elev / race_distance_km if race_distance_km else 0
                return {
                    'requires_user_decision': True,
                    'conflict': 'long_run_cap_below_race_target',
                    'race_target_km': round(target_long_run, 1),
                    'user_cap_km': max_lr_cap,
                    'target_long_run_elev_m': round(target_long_run * race_ratio, 0),
                    'options': ['raise_cap', 'accept_compromise', 'find_tuneup_race'],
                    'note': (
                        "User's max_long_run_km is below the race-derived peak "
                        "target. Do NOT regenerate silently. Explain the gap, "
                        "present the three options, and act on the user's choice. "
                        "Pass acknowledge_long_run_cap=true to proceed with the "
                        "current cap once the user picks accept_compromise."
                    ),
                }

    try:
        from services.plan_orchestrator import generate_plan_with_routes
        result = generate_plan_with_routes(
            user_id=user_id,
            total_weeks=tool_input['total_weeks'],
            race_distance_km=tool_input['race_distance_km'],
            race_elevation_m=tool_input['race_elevation_m'],
            race_date=tool_input['race_date'],
            athlete_weekly_km=tool_input['athlete_weekly_km'],
            athlete_weekly_elev=tool_input['athlete_weekly_elev'],
            athlete_longest_run_km=tool_input['athlete_longest_run_km'],
            athlete_category=tool_input['athlete_category'],
            long_run_day=tool_input['long_run_day'],
            rest_days=tool_input.get('rest_days', []),
            race_type=race_type,
            training_ratio=training_ratio,
            key_sections=key_sections,
            back_to_back=tool_input.get('back_to_back', False),
            overrides=tool_input.get('overrides'),
            strength_days=tool_input.get('strength_training_days', 0),
            strength_preferred_days=tool_input.get('strength_preferred_days'),
            prefs=prefs_dict,
        )
        weeks = result['weeks']
        route_match_summary = result['route_match_summary']
        warnings = result['warnings']
    except MissingPreferencesError as e:
        return {
            'requires_onboarding': True,
            'missing_fields': e.missing_fields,
        }
    except Exception as e:
        logger.exception(f"Plan engine failed: {e}")
        return {'error': f'Plan generation failed: {str(e)}'}

    # Cache validated weeks for save_training_plan
    _session_validated_weeks[user_id] = weeks
    _session_plan_warnings[user_id] = warnings

    # Cache race targets
    _session_race_targets[user_id] = {
        'distance_km': tool_input['race_distance_km'],
        'elevation_m': tool_input['race_elevation_m'],
    }

    # Build summary
    summary = []
    for w in weeks:
        summary.append({
            'week_number': w['week_number'],
            'theme': w['theme'],
            'total_km': w['total_km'],
            'total_elevation_m': w['total_elevation_m'],
            'long_run_km': next(
                (d['distance_km'] for d in w['days']
                 if d['workout_type'] in ('long_run', 'race_simulation')), 0
            ),
            'start_date': w.get('start_date', ''),
        })

    return {
        'status': 'generated',
        'total_weeks': len(weeks),
        'weeks': weeks,
        'summary': summary,
        'race_ratio_m_per_km': round(tool_input['race_elevation_m'] / tool_input['race_distance_km'], 1),
        'peak_long_run_km': max(s['long_run_km'] for s in summary),
        'peak_weekly_elev': max(s['total_elevation_m'] for s in summary),
        'route_match_summary': route_match_summary,
        'warnings': warnings,
        'note': 'Plan generated. Call save_training_plan to save it.',
    }


def _handle_get_plan_compliance(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Get compliance summary for the user's training plan."""
    from services.plan_compliance_service import PlanComplianceService

    plan_id = tool_input.get('plan_id')

    plan_repo = TrainingPlanRepository()

    if not plan_id:
        # Default to active plan
        active_plans = plan_repo.get_active_plans(user_id)
        plan = active_plans[0] if active_plans else None
        if not plan:
            return {'error': 'No active training plan found. The runner needs to activate a plan first.'}
        plan_id = plan.id
    else:
        plan = plan_repo.get_user_plan(plan_id, user_id)
        if not plan:
            return {'error': f'Plan {plan_id} not found.'}

    service = PlanComplianceService()
    summary = service.get_compliance_summary(plan_id, user_id)

    if not summary:
        return {'error': 'Could not compute compliance summary.'}

    # Enrich with volume stats
    total_planned_km = 0
    total_actual_km = 0
    missed_workouts = []

    for week in summary.get('weeks', []):
        for day in week.get('days', []):
            planned = day.get('planned', {})
            actual = day.get('actual')
            if planned.get('distance_km'):
                total_planned_km += planned['distance_km']
            if actual and actual.get('distance_km'):
                total_actual_km += actual['distance_km']
            if day.get('status') == 'missed':
                missed_workouts.append({
                    'week': week['week_number'],
                    'day': day['day'],
                    'workout_type': planned.get('workout_type'),
                    'distance_km': planned.get('distance_km'),
                })

    summary['volume_stats'] = {
        'total_planned_km': round(total_planned_km, 1),
        'total_actual_km': round(total_actual_km, 1),
        'volume_ratio': round(total_actual_km / total_planned_km, 2) if total_planned_km > 0 else None,
    }
    summary['missed_workouts'] = missed_workouts
    summary['plan_name'] = plan.plan_name
    summary['race_date'] = plan.race_date.isoformat() if plan.race_date else None

    return summary


def _handle_inspect_training_plan(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Inspect an entire training plan and return structured per-week analysis."""
    plan_id = tool_input.get('plan_id')
    plan_repo = TrainingPlanRepository()

    if not plan_id:
        active_plans = plan_repo.get_active_plans(user_id)
        plan = active_plans[0] if active_plans else None
        if not plan:
            # Fall back to most recent draft
            all_plans = plan_repo.get_user_plans(user_id)
            plan = all_plans[0] if all_plans else None
        if not plan:
            return {'error': 'No training plan found.'}
        plan_id = plan.id
    else:
        plan = plan_repo.get_user_plan(plan_id, user_id)
        if not plan:
            return {'error': f'Plan {plan_id} not found.'}

    weeks = plan.weeks or []
    if not weeks:
        return {'error': 'Plan has no weeks.'}

    # Get race elevation if target GPX is set
    race_elevation_m = None
    race_distance_km = None
    if plan.target_gpx_id:
        try:
            points, _bounds, error = _get_gpx_points(plan.target_gpx_id, user_id)
            if not error and points:
                race_distance_km = points[-1].get('distance', 0) / 1000
                race_elevation_m = _compute_gpx_elevation_gain(points)
        except Exception as e:
            logger.warning(f"inspect_training_plan: could not load race GPX data: {e}")

    week_summaries = []
    prev_km = None

    for week in weeks:
        wn = week.get('week_number', 0)
        theme = week.get('theme', '')
        days = week.get('days', [])

        total_km = sum(d.get('distance_km', 0) or 0 for d in days)
        total_elev = sum(d.get('elevation_m', 0) or 0 for d in days)

        # Long run stats
        long_runs = [d for d in days if d.get('workout_type') == 'long_run']
        long_run_km = max((d.get('distance_km', 0) or 0 for d in long_runs), default=0)
        long_run_elev = sum(d.get('elevation_m', 0) or 0 for d in long_runs)

        # Hard sessions (intensity-driven workouts)
        hard_types = {'intervals', 'hill_repeats', 'tempo', 'race_simulation', 'vert_session'}
        hard_sessions = [d for d in days if d.get('workout_type') in hard_types]
        hard_count = len(hard_sessions)
        hard_km = sum(d.get('distance_km', 0) or 0 for d in hard_sessions)
        hard_elev = sum(d.get('elevation_m', 0) or 0 for d in hard_sessions)

        # Easy / rest / recovery
        easy_types = {'easy', 'recovery', 'rest', 'cross_train'}
        easy_rest_count = len([d for d in days if d.get('workout_type') in easy_types])

        # Volume change from previous week
        volume_change_pct = None
        if prev_km is not None and prev_km > 0:
            volume_change_pct = round((total_km - prev_km) / prev_km * 100, 1)
        prev_km = total_km

        # Intensity ratio (hard sessions km / total km)
        intensity_ratio = round(hard_km / total_km * 100, 1) if total_km > 0 else 0

        summary = {
            'week_number': wn,
            'theme': theme,
            'total_km': round(total_km, 1),
            'total_elevation_m': round(total_elev),
            'long_run_km': round(long_run_km, 1),
            'long_run_elevation_m': round(long_run_elev),
            'hard_sessions': hard_count,
            'hard_session_types': [d.get('workout_type') for d in hard_sessions],
            'hard_km': round(hard_km, 1),
            'hard_elevation_m': round(hard_elev),
            'easy_rest_days': easy_rest_count,
            'intensity_ratio_pct': intensity_ratio,
            'volume_change_pct': volume_change_pct,
        }
        week_summaries.append(summary)

    # Plan-level analysis and warnings
    warnings = []
    total_weeks_count = len(week_summaries)

    for ws in week_summaries:
        wn = ws['week_number']
        theme = ws['theme']
        is_recovery = _is_recovery_week(theme)

        # >10% volume jump (except week 1 and recovery weeks)
        if ws['volume_change_pct'] is not None and ws['volume_change_pct'] > 15 and not is_recovery:
            warnings.append(
                f"Week {wn}: volume jumps {ws['volume_change_pct']}% from previous week "
                f"(guideline: <=10%). Risk of overuse injury."
            )

        # Recovery week with hard sessions
        if is_recovery and ws['hard_sessions'] > 0:
            warnings.append(
                f"Week {wn} ({theme}): has {ws['hard_sessions']} hard session(s) "
                f"({', '.join(ws['hard_session_types'])}). Recovery weeks should be easy only."
            )

        # Non-recovery week without long run
        if not is_recovery and ws['long_run_km'] == 0:
            # Allow last week (race week) to skip long run if it has race_simulation
            has_race = 'race_simulation' in ws.get('hard_session_types', [])
            if not has_race:
                warnings.append(
                    f"Week {wn}: no long run scheduled. The weekly long run is the "
                    f"cornerstone of endurance training."
                )

        # Non-recovery week without any intensity
        if not is_recovery and ws['hard_sessions'] == 0:
            warnings.append(
                f"Week {wn}: no speed/intensity session. At least one tempo, "
                f"interval, or hill repeat is needed per week."
            )

        # 80/20 rule: intensity ratio should be roughly 20% or less of volume
        if not is_recovery and ws['intensity_ratio_pct'] > 35:
            warnings.append(
                f"Week {wn}: {ws['intensity_ratio_pct']}% of volume is hard effort. "
                f"Recommended: <=20-25% (80/20 rule). Too much intensity increases injury risk."
            )

    # Taper assessment: last 1-2 weeks before race
    if total_weeks_count >= 3:
        peak_km = max(ws['total_km'] for ws in week_summaries)
        last_week = week_summaries[-1]
        second_last = week_summaries[-2]

        # Check if final week has proper volume reduction
        if last_week['total_km'] > 0 and peak_km > 0:
            taper_ratio = last_week['total_km'] / peak_km
            if taper_ratio > 0.7:
                warnings.append(
                    f"Week {last_week['week_number']} (race week): volume is "
                    f"{round(taper_ratio * 100)}% of peak ({last_week['total_km']}km vs "
                    f"{peak_km}km peak). Taper should reduce to 30-50% of peak."
                )

    # Elevation specificity vs race
    if race_elevation_m and race_elevation_m > 0:
        peak_weekly_elev = max(ws['total_elevation_m'] for ws in week_summaries)
        elev_ratio = peak_weekly_elev / race_elevation_m
        if elev_ratio < 0.4:
            warnings.append(
                f"Peak weekly elevation ({peak_weekly_elev}m) is only "
                f"{round(elev_ratio * 100)}% of race D+ ({round(race_elevation_m)}m). "
                f"Target 50-80% of race D+ in peak weeks."
            )

    # Build response
    result = {
        'plan_id': plan.id,
        'plan_name': plan.plan_name,
        'status': plan.status,
        'race_date': plan.race_date.isoformat() if plan.race_date else None,
        'total_weeks': total_weeks_count,
        'weeks': week_summaries,
        'warnings': warnings,
    }

    if race_elevation_m:
        result['race_elevation_m'] = round(race_elevation_m)
    if race_distance_km:
        result['race_distance_km'] = round(race_distance_km, 1)

    # Plan totals
    result['plan_totals'] = {
        'total_km': round(sum(ws['total_km'] for ws in week_summaries), 1),
        'total_elevation_m': round(sum(ws['total_elevation_m'] for ws in week_summaries)),
        'total_hard_sessions': sum(ws['hard_sessions'] for ws in week_summaries),
        'peak_weekly_km': round(max(ws['total_km'] for ws in week_summaries), 1),
        'peak_weekly_elevation_m': round(max(ws['total_elevation_m'] for ws in week_summaries)),
    }

    return result


def _handle_adjust_training_week(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Modify workouts in a future week of a training plan. Premium only."""
    import copy
    from datetime import timedelta
    from services.plan_compliance_service import PlanComplianceService
    from models.user_subscription import UserSubscription

    # Premium gate (bypassed in dev mode)
    import os
    dev_mode = os.environ.get('FLASK_ENV') == 'development'
    sub = UserSubscription.get_or_create(user_id)
    if not sub.is_premium and not dev_mode:
        return {
            'error': 'Adaptive plan adjustments are a Premium feature. '
                     'Upgrade to Premium to let the coach modify your training plan.',
            'upgrade_required': True,
        }

    plan_id = tool_input.get('plan_id')
    week_number = tool_input.get('week_number')
    days_input = tool_input.get('days', [])

    if not plan_id or not week_number:
        return {'error': 'plan_id and week_number are required.'}

    plan_repo = TrainingPlanRepository()
    plan = plan_repo.get_user_plan(plan_id, user_id)
    if not plan:
        return {'error': f'Plan {plan_id} not found.'}

    # Validate week is in the future
    compliance_service = PlanComplianceService()
    plan_start = compliance_service._get_plan_start_date(plan)
    today = datetime.now(timezone.utc).date()
    week_start = plan_start + timedelta(weeks=week_number - 1)

    if week_start < today:
        return {'error': f'Week {week_number} starts on {week_start.isoformat()} which is in the past. Only future weeks can be modified.'}

    # Find the week in plan data
    weeks = copy.deepcopy(plan.weeks or [])
    week = next((w for w in weeks if w.get('week_number') == week_number), None)
    if not week:
        return {'error': f'Week {week_number} not found in plan.'}

    VALID_TYPES = {'easy', 'tempo', 'intervals', 'long_run', 'hill_repeats', 'rest', 'cross_train', 'recovery', 'vert_session', 'back_to_back', 'race_simulation', 'strength'}
    EDITABLE_FIELDS = {'workout_type', 'title', 'distance_km', 'duration_min', 'elevation_m', 'notes', 'steps'}

    # Apply modifications
    before_days = {d['day']: dict(d) for d in week.get('days', [])}
    for mod in days_input:
        day_name = mod.get('day')
        if not day_name:
            continue

        day = next((d for d in week.get('days', []) if d.get('day') == day_name), None)
        if not day:
            continue

        for field in EDITABLE_FIELDS:
            if field in mod:
                if field == 'workout_type' and mod[field] not in VALID_TYPES:
                    continue
                day[field] = mod[field]

        # Rest/cross-train/strength days: zero out distance, elevation, duration, steps
        if day.get('workout_type') in ('rest', 'cross_train', 'strength'):
            day['distance_km'] = 0
            day['elevation_m'] = 0
            day['duration_min'] = 0
            day.pop('steps', None)

    # Recalculate week totals
    total_km = sum(d.get('distance_km', 0) or 0 for d in week.get('days', []))
    total_elev = sum(d.get('elevation_m', 0) or 0 for d in week.get('days', []))
    week['total_km'] = round(total_km, 1)
    week['total_elevation_m'] = round(total_elev)

    # Save — flag_modified ensures SQLAlchemy detects the JSON change
    from sqlalchemy.orm.attributes import flag_modified
    plan.weeks = weeks
    flag_modified(plan, 'weeks')
    plan_repo.commit()
    logger.info(f"adjust_training_week: saved week {week_number} for plan {plan_id}")

    # Build before/after comparison
    after_days = {d['day']: dict(d) for d in week.get('days', [])}
    changes = []
    for day_name in after_days:
        before = before_days.get(day_name, {})
        after = after_days[day_name]
        day_changes = {}
        for field in EDITABLE_FIELDS:
            if before.get(field) != after.get(field):
                day_changes[field] = {'before': before.get(field), 'after': after.get(field)}
        if day_changes:
            changes.append({'day': day_name, 'changes': day_changes})

    # Assess impact of the edit on training quality
    impact = _assess_edit_impact(before_days, after_days, week_number,
                                 week.get('theme', ''))

    result = {
        'status': 'updated',
        'plan_id': plan_id,
        'week_number': week_number,
        'changes': changes,
        'updated_week': week,
    }
    if impact.get('warnings'):
        result['edit_impact'] = impact
    return result


def _handle_get_plan_templates(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Return available plan templates or detail for a specific one."""
    from services.plan_templates import get_templates, get_template_detail

    template_id = tool_input.get('template_id')
    if template_id:
        detail = get_template_detail(template_id)
        if not detail:
            return {'error': f'Template "{template_id}" not found.'}
        return {'template': detail}

    return {'templates': get_templates()}


def _handle_get_season_overview(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Get season overview with all planned races."""
    from services.season_planning_service import SeasonPlanningService
    service = SeasonPlanningService()
    return service.get_season_overview(user_id)


def _handle_get_training_preferences(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Load user's saved training preferences."""
    from repositories import UserTrainingPreferencesRepository

    repo = UserTrainingPreferencesRepository()
    prefs = repo.get_by_user(user_id)
    if not prefs:
        return {
            'preferences': None,
            'note': 'No saved preferences. Ask the user about their training constraints.',
        }
    return {'preferences': prefs.to_dict()}


ALLOWED_PREFS_FIELDS = {
    'long_run_day', 'back_to_back', 'rest_days', 'mountain_days',
    'max_hours_per_day', 'strength_training_days', 'strength_preferred_days',
    # Capacity caps
    'max_weekly_km', 'max_long_run_km', 'max_long_run_hours',
    # Mountain budget
    'mountain_access_per_week', 'mountain_access_per_month',
    'max_mountain_elevation_m', 'max_mountain_distance_km',
    'sample_mountain_route_id',
    # Terrain
    'terrain_profile',
    # Pace-zone derivation (#61)
    'pace_zone_method', 'pace_zone_race_distance_m', 'pace_zone_race_time_s',
    # Heart-rate anchors (#59)
    'hr_max', 'hr_rest', 'lthr',
}

# Physiologically plausible bpm bounds for HR anchors.
_HR_ANCHOR_BOUNDS = {'hr_max': (100, 240), 'hr_rest': (25, 120), 'lthr': (80, 230)}


def _handle_save_training_preferences(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Save or update user's training preferences."""
    from repositories import UserTrainingPreferencesRepository

    clean = {k: v for k, v in tool_input.items() if k in ALLOWED_PREFS_FIELDS}

    # Setting terrain_profile explicitly marks the source as 'user' so future
    # automatic inferences won't overwrite the choice.
    if 'terrain_profile' in clean:
        clean['terrain_profile_source'] = 'user'

    if 'pace_zone_method' in clean:
        from models import UserTrainingPreferences
        if clean['pace_zone_method'] not in UserTrainingPreferences.VALID_PACE_ZONE_METHODS:
            return {'error': "pace_zone_method must be one of 'physics', 'vdot', 'riegel'"}

    for field, (lo, hi) in _HR_ANCHOR_BOUNDS.items():
        if field in clean and clean[field] is not None:
            try:
                clean[field] = int(clean[field])
            except (TypeError, ValueError):
                return {'error': f'{field} must be an integer bpm'}
            if not (lo <= clean[field] <= hi):
                return {'error': f'{field} must be between {lo} and {hi} bpm'}

    repo = UserTrainingPreferencesRepository()
    prefs = repo.upsert(user_id, clean)
    repo.commit()
    return {'preferences': prefs.to_dict(), 'status': 'saved'}


def _handle_raise_long_run_cap(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Update UserTrainingPreferences.max_long_run_km after the user agrees
    to raise their cap in response to a long_run_cap_below_race_target conflict.
    """
    from repositories import UserTrainingPreferencesRepository

    new_km = tool_input.get('new_km')
    try:
        new_km = float(new_km)
    except (TypeError, ValueError):
        return {'error': 'new_km must be a number'}
    if not (5 < new_km <= 80):
        return {'error': 'new_km must be in (5, 80] km'}

    repo = UserTrainingPreferencesRepository()
    prefs = repo.upsert(user_id, {'max_long_run_km': new_km})
    repo.commit()
    return {
        'status': 'updated',
        'max_long_run_km': prefs.max_long_run_km,
        'note': (
            'Cap updated. Re-call generate_full_plan with the same arguments '
            'to regenerate the plan using the new cap.'
        ),
    }


def _handle_search_tuneup_races(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Find candidate B/C tune-up races near the user's training base that
    can substitute a peak long run when their max_long_run_km is below the
    race-derived target.
    """
    from repositories import UserRepository
    from services.race_calendar_service import find_races

    target_distance_km = tool_input.get('target_distance_km')
    target_elev_m = tool_input.get('target_elev_m')
    window_start = tool_input.get('window_start')
    window_end = tool_input.get('window_end')
    if not (target_distance_km and window_start and window_end):
        return {'error': 'target_distance_km, window_start, window_end are required'}

    user = UserRepository().get_by_id(user_id)
    lat = user.training_base_lat if user else None
    lon = user.training_base_lon if user else None
    location_name = user.training_base_name if user else None

    # max_travel_km override: explicit > saved preference > default 100km.
    max_travel_override = tool_input.get('max_travel_km')
    if max_travel_override is not None:
        try:
            radius_km = float(max_travel_override)
            if radius_km <= 0:
                radius_km = (user.training_travel_radius_km if user else None) or 100
        except (TypeError, ValueError):
            radius_km = (user.training_travel_radius_km if user else None) or 100
    else:
        radius_km = (user.training_travel_radius_km if user else None) or 100

    if lat is None or lon is None:
        # Caller (the agent) must collect a location from the user; surface
        # the gap rather than guessing.
        return {
            'requires_location': True,
            'note': (
                "User has no training_base set. Ask the user for a city or "
                "region, then call again with country and an explicit "
                "lat/lon (or pass via tool_input.location_name)."
            ),
        }

    try:
        races = find_races(
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            target_distance_km=float(target_distance_km),
            target_elev_m=float(target_elev_m) if target_elev_m else None,
            window_start=window_start,
            window_end=window_end,
            country=tool_input.get('country'),
        )
    except Exception as e:
        logger.exception(f"race_calendar_service failed: {e}")
        return {'races': [], 'error': 'calendar_unavailable'}

    return {
        'location_name': location_name,
        'training_base': {'lat': lat, 'lon': lon},
        'radius_km': radius_km,
        'races': races[:10],
        'note': (
            "Pick top candidates by fit_score. Confirm one with the user, "
            "then re-call generate_full_plan with acknowledge_long_run_cap=true."
        ),
    }


def _handle_start_onboarding_questionnaire(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Build the onboarding wizard schema for the frontend modal.

    Time-first redesign: hours are the primary input, km caps are derived.
    Pre-fills slider defaults from `infer_capacity` when the user has enough
    Strava history; falls back to conservative defaults at low confidence.
    """
    from repositories import UserTrainingPreferencesRepository
    from services.terrain_profile_service import infer_user_terrain_profile
    from services.training_capacity_inference import infer_capacity

    inferred = infer_user_terrain_profile(user_id)
    prefs = UserTrainingPreferencesRepository().get_by_user(user_id)
    has_mountain_activity = (inferred.get('max_single_run_elev') or 0) >= 300

    capacity = infer_capacity(user_id)

    DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    inferred_profile = inferred.get('profile') or 'rolling_hills'
    median_density = inferred.get('median_elev_density') or 0
    sample_count = inferred.get('sample_count') or 0

    # Banner shown to the user based on confidence band.
    confidence = capacity.get('confidence', 'low')
    if confidence == 'high':
        capacity_banner = None
    elif confidence == 'medium':
        capacity_banner = (
            f"Stima da {capacity.get('sample_size_weeks', 0)} settimane di Strava — "
            f"modifica se non corrisponde."
        )
    else:
        capacity_banner = (
            "Non ho abbastanza storico Strava per stimare il tuo budget — "
            "compila tu i campi qui sotto."
        )

    return {
        'requires_ui': True,
        'wizard_id': 'training_preferences_v2',
        'inferred': inferred,
        'capacity': capacity,
        'capacity_banner': capacity_banner,
        'current': prefs.to_dict() if prefs else {},
        'requires_sample_route': not has_mountain_activity,
        'steps': [
            {
                'id': 'time_budget',
                'banner': capacity_banner,
                'fields': [
                    {'key': 'available_hours_per_week', 'type': 'number',
                     'min': 3, 'max': 15, 'step': 0.5,
                     'default': capacity.get('available_hours_per_week'),
                     'label_it': 'Quante ore alla settimana puoi allenarti?',
                     'help_it': 'Considera la settimana media realistica.'},
                    {'key': 'usual_midweek_hours', 'type': 'number',
                     'min': 0.5, 'max': 2.5, 'step': 0.25,
                     'default': capacity.get('usual_midweek_hours'),
                     'label_it': 'Durata tipica di una sessione infrasettimanale (ore)?'},
                    {'key': 'max_long_run_hours', 'type': 'number',
                     'min': 1, 'max': 8, 'step': 0.25,
                     'default': capacity.get('max_long_run_hours'),
                     'label_it': 'Tempo massimo del lungo (ore)?',
                     'help_it': (
                         'Il lungo più lungo che riesci a fare da solo. Vincolo '
                         'primario: km e D+ derivano da qui.'
                     )},
                    {'key': 'long_run_day', 'type': 'select',
                     'options': ['Saturday', 'Sunday', 'Friday', 'Monday'],
                     'default': capacity.get('long_run_day_inferred'),
                     'label_it': 'Quando fai il lungo?'},
                ],
            },
            {
                'id': 'mountain',
                'fields': [
                    {'key': 'mountain_access_per_week', 'type': 'number',
                     'min': 0, 'max': 7, 'step': 0.5,
                     'default': capacity.get('mountain_runs_per_week'),
                     'label_it': 'Quante volte alla settimana puoi raggiungere la montagna?',
                     'help_it': 'Usa 0.5 per "una volta ogni 2 settimane".'},
                    {'key': 'mountain_days', 'type': 'multiselect',
                     'options': DAYS,
                     'default': capacity.get('mountain_days_inferred') or [],
                     'label_it': 'In quali giorni puoi andare in montagna?'},
                    {'key': 'max_mountain_hours_per_outing', 'type': 'number',
                     'min': 1, 'max': 10, 'step': 0.25,
                     'default': capacity.get('usual_mountain_hours'),
                     'label_it': 'Tempo massimo per uscita mountain (ore)?'},
                    {'key': 'max_mountain_elevation_m', 'type': 'number',
                     'min': 0, 'max': 5000,
                     'label_it': 'Dislivello max raggiungibile in una uscita (m D+)?'},
                ],
            },
            {
                'id': 'terrain',
                'fields': [
                    {'key': 'terrain_profile', 'type': 'select',
                     'options': ['flat_urban', 'rolling_hills', 'mountain'],
                     'default': inferred_profile,
                     'label_it': 'Confermi il profilo del tuo terreno abituale?',
                     'help_it': (
                         f"Inferito da {sample_count} attività recenti "
                         f"(mediana {median_density:.0f} m/km)."
                     )},
                ],
            },
            {
                'id': 'sample_route',
                'conditional': 'requires_sample_route',
                'fields': [
                    {'key': 'sample_mountain_route_id', 'type': 'route_picker',
                     'label_it': 'Tracciami un percorso tipo per la montagna',
                     'help_it': (
                         "Non vediamo attività con D+ > 300m nei tuoi import. "
                         "Carica un GPX o genera un percorso campione."
                     ),
                     'cta_actions': [
                         {'action': 'upload', 'label_it': 'Carica GPX'},
                         {'action': 'generate', 'label_it': 'Genera con ORS',
                          'tool': 'generate_training_route'},
                     ]},
                ],
            },
        ],
    }


def _handle_preview_capacity(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Convert an hours-budget into expected km / D+ for the calling user.

    Used for chat hypotheticals ("if I add 1h to Saturday, how many km?")
    and to verify the wizard preview server-side. Falls back to default
    physics constants when UserLearnedParams is missing.
    """
    from services.physics_model.time_budget import (
        predict_distance_for_time,
        predict_time_for_distance,
    )

    available = float(tool_input.get('available_hours_per_week') or 0)
    midweek = float(tool_input.get('usual_midweek_hours') or 0)
    long_run = float(tool_input.get('max_long_run_hours') or 0)
    ratio = float(tool_input.get('training_ratio_m_per_km') or 30.0)

    if available <= 0 or long_run <= 0:
        return {
            'error': 'available_hours_per_week and max_long_run_hours must be > 0',
        }

    learned = None
    try:
        from repositories import UserLearnedParamsRepository
        learned = UserLearnedParamsRepository().get_by_user(user_id)
    except Exception:
        # No flask context / no calibration yet — defaults are fine.
        learned = None

    weekly_km, weekly_elev = predict_distance_for_time(
        available, ratio, learned_params=learned, effort='easy'
    )
    long_run_km, long_run_elev = predict_distance_for_time(
        long_run, ratio, learned_params=learned, effort='long_run'
    )
    midweek_km = midweek_elev = 0.0
    if midweek > 0:
        midweek_km, midweek_elev = predict_distance_for_time(
            midweek, ratio, learned_params=learned, effort='easy'
        )

    return {
        'inputs': {
            'available_hours_per_week': available,
            'usual_midweek_hours': midweek,
            'max_long_run_hours': long_run,
            'training_ratio_m_per_km': ratio,
        },
        'weekly': {
            'km': weekly_km,
            'elevation_m': weekly_elev,
        },
        'long_run': {
            'km': long_run_km,
            'elevation_m': long_run_elev,
            'estimated_hours': round(
                predict_time_for_distance(
                    long_run_km, long_run_elev, learned_params=learned,
                    effort='long_run',
                ),
                2,
            ),
        },
        'midweek_session': {
            'km': midweek_km,
            'elevation_m': midweek_elev,
        },
        'learned_params_used': learned is not None,
    }


def _handle_infer_terrain_profile(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Thin wrapper around the terrain profile inference service."""
    from services.terrain_profile_service import infer_user_terrain_profile

    lookback = tool_input.get('lookback_days') or 90
    return infer_user_terrain_profile(user_id, lookback_days=lookback)


def _handle_match_routes_to_plan(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Bind real TrainingRoute records to every running day of an existing plan."""
    from repositories import TrainingPlanRepository, UserTrainingPreferencesRepository
    from services.route_matcher import match_routes_to_plan

    plan_id = tool_input.get('plan_id')
    if not plan_id:
        return {'error': 'plan_id required'}

    plan_repo = TrainingPlanRepository()
    plan = plan_repo.find_one_by(id=plan_id, user_id=user_id)
    if not plan:
        return {'error': 'plan not found'}

    prefs = UserTrainingPreferencesRepository().get_by_user(user_id)

    summary = match_routes_to_plan(plan, prefs)
    try:
        plan_repo.commit()
    except Exception as e:
        plan_repo.rollback()
        logger.exception(f"match_routes_to_plan: commit failed for plan {plan_id}: {e}")
        return {'error': f'Failed to persist route matches: {e}'}

    return {
        'status': 'matched',
        'plan_id': plan.id,
        'summary': summary,
    }

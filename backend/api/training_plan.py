"""Training Plan CRUD API with compliance tracking."""

import copy
import logging
import re
from flask import Blueprint, request, jsonify
from api.utils import get_current_user
from api.billing import requires_premium
from repositories import (
    TrainingPlanRepository,
    SubscriptionRepository,
    PredictionRepository,
    UserTrainingPreferencesRepository,
    UserLearnedParamsRepository,
    DailyCheckinRepository,
    PlanAdjustmentRepository,
    ActivityRepository,
)

logger = logging.getLogger(__name__)

bp = Blueprint('training_plan', __name__, url_prefix='/api/training-plan')

training_plan_repo = TrainingPlanRepository()
subscription_repo = SubscriptionRepository()
prediction_repo = PredictionRepository()
prefs_repo = UserTrainingPreferencesRepository()
learned_params_repo = UserLearnedParamsRepository()
checkin_repo = DailyCheckinRepository()
adjustment_repo = PlanAdjustmentRepository()
strava_activity_repo = ActivityRepository()

VALID_WORKOUT_TYPES = {
    'easy', 'tempo', 'intervals', 'long_run', 'hill_repeats',
    'rest', 'cross_train', 'recovery',
    'vert_session', 'back_to_back', 'race_simulation', 'strength',
}

EDITABLE_DAY_FIELDS = {
    'workout_type', 'title', 'distance_km', 'duration_min',
    'elevation_m', 'intensity', 'notes', 'steps', 'route_id',
}

# Numeric day-fields that must coerce cleanly before being written into the
# weeks JSON. Without this, a stringy "10" from a careless caller is stored
# as-is, then crashes the per-week totals sum() at the bottom of
# update_workout_day with a TypeError.
DAY_FIELD_NUMERIC_BOUNDS = {
    'distance_km':  (float, 0, 100),
    'duration_min': (float, 0, 1440),
    'elevation_m':  (float, 0, 10000),
    'intensity':    (float, 0, 10),
}


@bp.route('/', methods=['GET'])
def list_plans():
    """List user's training plans (summaries)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plans = training_plan_repo.get_user_plans(user.id)
    return jsonify({'plans': [p.to_summary() for p in plans]})


@bp.route('/<int:plan_id>', methods=['GET'])
def get_plan(plan_id):
    """Get full training plan with weeks."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    return jsonify(plan.to_dict())


@bp.route('/<int:plan_id>', methods=['PUT'])
def update_plan(plan_id):
    """Update a training plan."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'plan_name' in data:
        if not isinstance(data['plan_name'], str) or not data['plan_name'].strip():
            return jsonify({'error': 'plan_name must be a non-empty string'}), 400
        # plan_name is db.String(255); pre-validate so the DB doesn't have to.
        plan.plan_name = data['plan_name'].strip()[:255]
    if 'status' in data and data['status'] in ('draft', 'active', 'completed'):
        plan.status = data['status']
    if 'race_priority' in data:
        if data['race_priority'] in ('A', 'B', 'C', None):
            plan.race_priority = data['race_priority']
    if 'weeks' in data:
        if not isinstance(data['weeks'], list):
            return jsonify({'error': 'weeks must be a list'}), 400
        plan.weeks = data['weeks']

    training_plan_repo.commit()
    return jsonify(plan.to_dict())


@bp.route('/<int:plan_id>/weeks/<int:week_number>/days/<day_name>', methods=['PATCH'])
def update_workout_day(plan_id, week_number, day_name):
    """Update a single workout day within a plan.

    PATCH /api/training-plan/1/weeks/2/days/Monday
    Body: {"distance_km": 10, "workout_type": "tempo", "title": "Tempo run"}
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Validate workout_type if provided
    if 'workout_type' in data and data['workout_type'] not in VALID_WORKOUT_TYPES:
        return jsonify({'error': f'Invalid workout_type. Must be one of: {", ".join(sorted(VALID_WORKOUT_TYPES))}'}), 400

    # Coerce + range-check numeric fields. Storing a non-numeric value here
    # (e.g. "10" from a stringly-typed caller) crashes the week-totals sum()
    # below with a TypeError.
    for field, (caster, lo, hi) in DAY_FIELD_NUMERIC_BOUNDS.items():
        if field in data and data[field] is not None:
            try:
                coerced = caster(data[field])
            except (TypeError, ValueError):
                return jsonify({'error': f'{field} must be numeric'}), 400
            if not (lo <= coerced <= hi):
                return jsonify({'error': f'{field} must be between {lo} and {hi}'}), 400
            data[field] = coerced

    # Validate steps if provided
    if 'steps' in data and data['steps'] is not None:
        from services.workout_service import validate_steps
        valid, err = validate_steps(data['steps'])
        if not valid:
            return jsonify({'error': f'Invalid steps: {err}'}), 400

    # Find the week
    weeks = copy.deepcopy(plan.weeks or [])
    week = next((w for w in weeks if w.get('week_number') == week_number), None)
    if not week:
        return jsonify({'error': f'Week {week_number} not found'}), 404

    # Find the day
    day = next((d for d in week.get('days', []) if d.get('day') == day_name), None)
    if not day:
        return jsonify({'error': f'Day {day_name} not found in week {week_number}'}), 404

    # Apply updates (only allowed fields)
    before = dict(day)
    for field in EDITABLE_DAY_FIELDS:
        if field in data:
            day[field] = data[field]

    # Auto-compute summaries from steps if steps were provided
    if 'steps' in data and data['steps']:
        from services.workout_service import compute_step_summaries
        summaries = compute_step_summaries(data['steps'])
        if summaries['distance_km'] is not None:
            day['distance_km'] = summaries['distance_km']
        if summaries['duration_min'] is not None:
            day['duration_min'] = summaries['duration_min']
        if summaries['elevation_m'] is not None:
            day['elevation_m'] = summaries['elevation_m']

    from services.route_matcher import rematch_day_if_changed
    rematch_day_if_changed(plan.user_id, day, before)

    # Recalculate week totals
    total_km = sum(d.get('distance_km', 0) or 0 for d in week.get('days', []))
    total_elev = sum(d.get('elevation_m', 0) or 0 for d in week.get('days', []))
    week['total_km'] = round(total_km, 1)
    week['total_elevation_m'] = round(total_elev)

    # Save — reassign to trigger SQLAlchemy change detection on JSON column
    plan.weeks = weeks
    training_plan_repo.commit()

    return jsonify({'day': day, 'week_totals': {'total_km': week['total_km'], 'total_elevation_m': week['total_elevation_m']}})


@bp.route('/<int:plan_id>/weeks/<int:week_number>/days/<day_name>/location', methods=['PUT'])
def set_day_location_route(plan_id, week_number, day_name):
    """Set the training location of one workout and re-match its route.

    Body: {"location_id": 3} (null clears the override: weekday location applies).
    """
    from services.route_matcher import set_day_location
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404
    try:
        day = set_day_location(plan, week_number, day_name,
                               (request.get_json() or {}).get('location_id'),
                               prefs=prefs_repo.get_by_user(user.id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    if day is None:
        return jsonify({'error': 'Day not found'}), 404
    training_plan_repo.commit()
    return jsonify({'day': day})


@bp.route('/parse-workout', methods=['POST'])
def parse_workout_text():
    """Parse PaceMind workout syntax into structured steps + predicted durations.

    Body: {"text": "Warmup 15min Z2\\n4x:\\n  1km +80m @ 4:30/km\\n  Recovery 3min Z1\\n..."}
    Returns: {steps, summary, errors, valid}

    Used for live preview in the workout text editor. Predictions use the
    requesting user's calibrated physics params (or defaults).
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    text = data.get('text', '')
    if not isinstance(text, str):
        return jsonify({'error': 'text must be a string'}), 400

    from services.workout_service import (
        text_to_steps,
        validate_steps,
        compute_step_summaries,
        predict_steps_durations,
    )

    steps, parse_errors = text_to_steps(text)

    # Resolve physics params for time prediction (falls back to defaults internally)
    params = None
    learned = learned_params_repo.get_for_user(user.id)
    if learned:
        params = learned.to_dict()
    elif user.saved_flat_pace:
        # saved_flat_pace is in min/km -> convert to v_flat (m/s)
        try:
            v_flat = 1000.0 / (float(user.saved_flat_pace) * 60.0)
            params = {'v_flat': v_flat}
        except (TypeError, ValueError, ZeroDivisionError):
            params = None

    steps_with_durations = predict_steps_durations(steps, params)

    valid = True
    schema_error = None
    if steps_with_durations:
        ok, err = validate_steps(steps_with_durations)
        if not ok:
            valid = False
            schema_error = err

    summary = compute_step_summaries(steps_with_durations) if steps_with_durations else {
        'distance_km': None, 'duration_min': None, 'elevation_m': None, 'step_count': 0
    }

    return jsonify({
        'steps': steps_with_durations,
        'summary': summary,
        'errors': parse_errors,
        'valid': valid and not parse_errors,
        'schema_error': schema_error,
    })


# ---------------------------------------------------------------------------
# Calendar surface (aggregates days across all of a user's plans)
# ---------------------------------------------------------------------------

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _iso_date_or_none(value):
    from datetime import date, datetime
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _day_calendar_date(week, day_obj):
    """Resolve a calendar date for a day, preferring an explicit day.date,
    falling back to week.start_date + day-index."""
    from datetime import timedelta
    explicit = _iso_date_or_none(day_obj.get('date'))
    if explicit:
        return explicit
    week_start = _iso_date_or_none(week.get('start_date'))
    if not week_start:
        return None
    name = day_obj.get('day')
    if name not in DAY_NAMES:
        return None
    return week_start + timedelta(days=DAY_NAMES.index(name))


@bp.route('/calendar', methods=['GET'])
def get_calendar():
    """Aggregated calendar across all of the current user's plans.

    Query params: ?from=YYYY-MM-DD&to=YYYY-MM-DD (inclusive). Defaults to a
    window of [today - 14d, today + 84d] if missing.

    Returns:
      {
        days:  [{date, plan_id, plan_name, race_priority, ...day_fields}],
        races: [{plan_id, race_date, race_priority, plan_name, race_id}],
        window: {from, to}
      }
    """
    from datetime import date, timedelta
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    today = date.today()
    try:
        from_d = _iso_date_or_none(request.args.get('from')) or (today - timedelta(days=14))
        to_d = _iso_date_or_none(request.args.get('to')) or (today + timedelta(days=84))
    except Exception:
        return jsonify({'error': 'invalid date params'}), 400
    if to_d < from_d:
        return jsonify({'error': 'to must be >= from'}), 400

    plans = training_plan_repo.get_user_plans(user.id)

    days_out = []
    races_out = []
    for plan in plans:
        if plan.status == 'completed':
            continue
        race_date = _iso_date_or_none(plan.race_date)
        if race_date and from_d <= race_date <= to_d and plan.race_id:
            races_out.append({
                'plan_id': plan.id,
                'plan_name': plan.plan_name,
                'race_id': plan.race_id,
                'race_date': race_date.isoformat(),
                'race_priority': plan.race_priority,
            })

        for week in (plan.weeks or []):
            for day_obj in (week.get('days') or []):
                d_date = _day_calendar_date(week, day_obj)
                if not d_date or not (from_d <= d_date <= to_d):
                    continue
                # Only return days that actually have something to show.
                has_content = any(day_obj.get(k) for k in (
                    'workout_type', 'title', 'distance_km', 'duration_min',
                    'elevation_m', 'notes', 'steps', 'route_id'
                ))
                if not has_content:
                    continue
                days_out.append({
                    'date': d_date.isoformat(),
                    'plan_id': plan.id,
                    'plan_name': plan.plan_name,
                    'race_id': plan.race_id,
                    'race_priority': plan.race_priority,
                    'week_number': week.get('week_number'),
                    'day': day_obj.get('day'),
                    'workout_type': day_obj.get('workout_type'),
                    'title': day_obj.get('title'),
                    'distance_km': day_obj.get('distance_km'),
                    'duration_min': day_obj.get('duration_min'),
                    'elevation_m': day_obj.get('elevation_m'),
                    'intensity': day_obj.get('intensity'),
                    'notes': day_obj.get('notes'),
                    'steps': day_obj.get('steps'),
                    'route_id': day_obj.get('route_id'),
                    'route_match_quality': day_obj.get('route_match_quality'),
                    'location_id': day_obj.get('location_id'),
                    'resolved_location_id': day_obj.get('resolved_location_id'),
                })

    days_out.sort(key=lambda d: (d['date'], d['plan_id']))
    races_out.sort(key=lambda r: r['race_date'])

    # Done activities, so each calendar day links to its post-workout analysis.
    from datetime import datetime as _dt
    from models import Activity
    acts = (Activity.query.filter(Activity.user_id == user.id,
                                  Activity.start_date >= _dt.combine(from_d - timedelta(days=1), _dt.min.time()),
                                  Activity.start_date < _dt.combine(to_d + timedelta(days=2), _dt.min.time()))
            .order_by(Activity.start_date).all())
    activities_out = [{'id': a.id, 'date': a.local_date.isoformat(), 'name': a.name,
                       'distance_km': round((a.distance or 0) / 1000, 1),
                       'elevation_m': round(a.elevation_gain_m or 0)}
                      for a in acts if from_d <= a.local_date <= to_d]

    return jsonify({
        'days': days_out,
        'races': races_out,
        'activities': activities_out,
        'window': {'from': from_d.isoformat(), 'to': to_d.isoformat()},
    })


@bp.route('/calendar/days', methods=['POST'])
def add_calendar_workout():
    """Add or upsert a workout on a specific date.

    The plan it lands on is resolved automatically:
      - active race plan whose window covers `date` (preferred), or
      - the user's Personal plan (created on demand).

    Body: {date: 'YYYY-MM-DD', workout_type?, title?, distance_km?, duration_min?,
           elevation_m?, intensity?, notes?, steps?, route_id?}

    Returns: {plan_id, week_number, day, day_obj}
    """
    from datetime import timedelta
    from services.calendar_service import resolve_target_plan
    from services.workout_service import validate_steps as _vs, compute_step_summaries as _css

    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    target_date = _iso_date_or_none(data.get('date'))
    if not target_date:
        return jsonify({'error': 'date (YYYY-MM-DD) required'}), 400

    if 'workout_type' in data and data['workout_type'] not in VALID_WORKOUT_TYPES:
        return jsonify({'error': f'Invalid workout_type'}), 400

    for field, (caster, lo, hi) in DAY_FIELD_NUMERIC_BOUNDS.items():
        if field in data and data[field] is not None:
            try:
                coerced = caster(data[field])
            except (TypeError, ValueError):
                return jsonify({'error': f'{field} must be numeric'}), 400
            if not (lo <= coerced <= hi):
                return jsonify({'error': f'{field} must be between {lo} and {hi}'}), 400
            data[field] = coerced

    if 'steps' in data and data['steps'] is not None:
        ok, err = _vs(data['steps'])
        if not ok:
            return jsonify({'error': f'Invalid steps: {err}'}), 400

    plan = resolve_target_plan(user.id, target_date)

    weeks = copy.deepcopy(plan.weeks or [])

    # Find or create the week containing target_date (Monday-anchored).
    week_start = target_date - timedelta(days=target_date.weekday())
    week = None
    for w in weeks:
        ws = _iso_date_or_none(w.get('start_date'))
        if ws == week_start:
            week = w
            break

    if week is None:
        next_num = max((w.get('week_number') or 0 for w in weeks), default=0) + 1
        week = {
            'week_number': next_num,
            'start_date': week_start.isoformat(),
            'theme': '',
            'total_km': 0,
            'total_elevation_m': 0,
            'days': [],
        }
        weeks.append(week)
        weeks.sort(key=lambda w: _iso_date_or_none(w.get('start_date')) or week_start)
        # Re-number sequentially after sort
        for idx, w in enumerate(weeks, start=1):
            w['week_number'] = idx

    day_name = DAY_NAMES[target_date.weekday()]
    day = next((d for d in week.setdefault('days', []) if d.get('day') == day_name), None)
    if day is None:
        day = {'day': day_name, 'date': target_date.isoformat()}
        week['days'].append(day)
        week['days'].sort(key=lambda d: DAY_NAMES.index(d.get('day')) if d.get('day') in DAY_NAMES else 99)

    # Make sure the day carries an explicit calendar date (newer plans rely on it).
    day['date'] = target_date.isoformat()

    before = dict(day)
    for field in EDITABLE_DAY_FIELDS:
        if field in data:
            day[field] = data[field]

    if data.get('steps'):
        summaries = _css(data['steps'])
        if summaries['distance_km'] is not None:
            day['distance_km'] = summaries['distance_km']
        if summaries['duration_min'] is not None:
            day['duration_min'] = summaries['duration_min']
        if summaries['elevation_m'] is not None:
            day['elevation_m'] = summaries['elevation_m']

    from services.route_matcher import rematch_day_if_changed
    rematch_day_if_changed(plan.user_id, day, before)

    total_km = sum(d.get('distance_km', 0) or 0 for d in week.get('days', []))
    total_elev = sum(d.get('elevation_m', 0) or 0 for d in week.get('days', []))
    week['total_km'] = round(total_km, 1)
    week['total_elevation_m'] = round(total_elev)

    plan.weeks = weeks
    training_plan_repo.commit()

    return jsonify({
        'plan_id': plan.id,
        'plan_name': plan.plan_name,
        'race_id': plan.race_id,
        'week_number': week['week_number'],
        'day': day_name,
        'date': target_date.isoformat(),
        'day_obj': day,
    })


@bp.route('/calendar/move', methods=['POST'])
def move_calendar_workout():
    """Move a workout to another date of the same plan; swap if the target has one.

    Body: {from_date, to_date}. Returns {plan_id, from_date, to_date}.
    """
    from datetime import date, timedelta
    from services.calendar_service import resolve_target_plan
    from services.plan_adjustment_service import PlanAdjustmentService
    from services.route_matcher import rematch_stale_days

    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    from_d = _iso_date_or_none(data.get('from_date'))
    to_d = _iso_date_or_none(data.get('to_date'))
    if not from_d or not to_d:
        return jsonify({'error': 'from_date and to_date (YYYY-MM-DD) required'}), 400
    if from_d == to_d:
        return jsonify({'error': 'from_date and to_date must differ'}), 400
    if from_d < date.today() or to_d < date.today():
        return jsonify({'error': 'Cannot move workouts from or to past dates'}), 400

    plan = resolve_target_plan(user.id, from_d)
    if resolve_target_plan(user.id, to_d).id != plan.id:
        return jsonify({'error': 'Cannot move a workout to a different plan'}), 400

    weeks = copy.deepcopy(plan.weeks or [])

    def find_day(d, create=False):
        ws = (d - timedelta(days=d.weekday())).isoformat()
        week = next((w for w in weeks if w.get('start_date') == ws), None)
        if week is None and create:
            week = {'week_number': 0, 'start_date': ws, 'theme': '', 'total_km': 0,
                    'total_elevation_m': 0, 'days': []}
            weeks.append(week)
            weeks.sort(key=lambda w: w.get('start_date') or '')
            for i, w in enumerate(weeks, start=1):
                w['week_number'] = i
        if week is None:
            return None, None
        name = DAY_NAMES[d.weekday()]
        day = next((x for x in week.setdefault('days', []) if x.get('day') == name), None)
        if day is None and create:
            day = {'day': name, 'date': d.isoformat()}
            week['days'].append(day)
            week['days'].sort(key=lambda x: DAY_NAMES.index(x['day']) if x.get('day') in DAY_NAMES else 99)
        return week, day

    src_week, src = find_day(from_d)
    if not src or not src.get('workout_type'):
        return jsonify({'error': 'No workout on from_date'}), 400
    dst_week, dst = find_day(to_d, create=True)
    src['date'] = from_d.isoformat()
    dst['date'] = to_d.isoformat()

    PlanAdjustmentService._swap_day_payloads(src, dst)
    rematch_stale_days(user.id, [src, dst])

    for w in (src_week, dst_week):
        w['total_km'] = round(sum(d.get('distance_km', 0) or 0 for d in w.get('days', [])), 1)
        w['total_elevation_m'] = round(sum(d.get('elevation_m', 0) or 0 for d in w.get('days', [])))

    plan.weeks = weeks
    training_plan_repo.commit()
    return jsonify({'plan_id': plan.id, 'from_date': from_d.isoformat(), 'to_date': to_d.isoformat()})


@bp.route('/<int:plan_id>/compliance', methods=['GET'])
@requires_premium('plan_compliance')
def get_compliance(plan_id):
    """Get compliance summary for a training plan."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    from services.plan_compliance_service import PlanComplianceService
    service = PlanComplianceService()
    summary = service.get_compliance_summary(plan_id, user.id)

    if not summary:
        return jsonify({'error': 'Could not compute compliance'}), 500

    return jsonify(summary)


@bp.route('/<int:plan_id>/dashboard', methods=['GET'])
def get_dashboard(plan_id):
    """Get race dashboard data: plan + compliance + training load + prediction.

    Single endpoint that aggregates everything the Race Dashboard view needs,
    reducing frontend round-trips.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    from services.plan_compliance_service import PlanComplianceService
    from services.training_load_service import TrainingLoadService
    from datetime import datetime, timezone

    import os
    dev_mode = os.environ.get('FLASK_ENV') == 'development'
    sub = subscription_repo.get_or_create(user.id)
    is_premium = sub.is_premium or dev_mode

    # Compliance summary
    compliance_service = PlanComplianceService()
    compliance = compliance_service.get_compliance_summary(plan_id, user.id)

    # Free tier: only show current week compliance
    if not is_premium and compliance and compliance.get('weeks'):
        current_wk = compliance.get('current_week', 1)
        compliance['weeks'] = [
            w for w in compliance['weeks'] if w.get('week_number') == current_wk
        ]
        compliance['gated'] = True

    # Training load (ATL/CTL/TSB) — premium only
    training_load = None
    if is_premium:
        training_load_service = TrainingLoadService()
        try:
            training_load = training_load_service.get_training_load(user.id)
        except Exception:
            logger.warning("get_training_load failed for user_id=%s", user.id, exc_info=True)
            training_load = None

    # Race countdown. plan.race_date is db.DateTime so always datetime-or-None,
    # but be defensive in case a future migration loosens the type.
    race_countdown = None
    if plan.race_date:
        race_d = plan.race_date.date() if isinstance(plan.race_date, datetime) else plan.race_date
        race_countdown = max(0, (race_d - datetime.now(timezone.utc).date()).days)

    # Latest prediction time for target GPX
    predicted_time = None
    if plan.target_gpx_id:
        latest_pred = prediction_repo.get_latest_for_gpx(plan.target_gpx_id, user.id)
        if latest_pred:
            predicted_time = latest_pred.total_time_seconds if hasattr(latest_pred, 'total_time_seconds') else None

    # Prediction history — premium only
    prediction_history = (plan.prediction_history or []) if is_premium else []

    return jsonify({
        'plan': plan.to_dict(),
        'compliance': compliance,
        'training_load': training_load,
        'race_countdown': race_countdown,
        'predicted_time': predicted_time,
        'prediction_history': prediction_history,
        'is_premium': is_premium,
    })


@bp.route('/<int:plan_id>/export/ics', methods=['GET'])
def export_ics(plan_id):
    """Export training plan as ICS calendar file."""
    from flask import Response
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    from services.calendar_export_service import generate_ics
    ics_content = generate_ics(plan)

    # Sanitize: plan_name is user-controlled (PUT update_plan). Strip CR/LF
    # to prevent header injection, and quotes/backslashes/path separators
    # to keep the Content-Disposition value well-formed.
    safe_name = re.sub(r'[\r\n"\\/]+', '_', plan.plan_name).strip().replace(' ', '_')
    if not safe_name:
        safe_name = 'training_plan'
    filename = f"{safe_name[:200]}.ics"
    return Response(
        ics_content,
        mimetype='text/calendar',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@bp.route('/<int:plan_id>/export/intervals', methods=['POST'])
def export_intervals(plan_id):
    """Push the plan's workouts into the user's intervals.icu calendar.

    Body: {"api_key": "..."} from intervals.icu Settings > Developer. The key
    is used for this call only and never stored. Re-running updates the same
    events (upsert on external_id); intervals.icu then syncs them to the watch.
    """
    import requests
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404
    api_key = ((request.get_json(silent=True) or {}).get('api_key') or '').strip()
    if not api_key:
        return jsonify({'error': 'api_key required'}), 400

    from services.calendar_export_service import plan_to_icu_events
    events = plan_to_icu_events(plan)
    try:
        resp = requests.post(
            'https://intervals.icu/api/v1/athlete/0/events/bulk',
            params={'upsert': 'true'}, json=events,
            auth=('API_KEY', api_key), timeout=30,
        )
    except requests.RequestException:
        return jsonify({'error': 'intervals.icu unreachable'}), 502
    if resp.status_code in (401, 403):
        return jsonify({'error': 'intervals.icu rejected the API key'}), 400
    if not resp.ok:
        return jsonify({'error': f'intervals.icu error {resp.status_code}'}), 502
    return jsonify({'exported': len(events)})


@bp.route('/season', methods=['GET'])
def get_season():
    """Get season overview with all planned races."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from services.season_planning_service import SeasonPlanningService
    service = SeasonPlanningService()
    overview = service.get_season_overview(user.id)
    return jsonify(overview)


@bp.route('/<int:plan_id>/complete', methods=['POST'])
@requires_premium('race_report')
def complete_plan(plan_id):
    """Complete a race and generate post-race report."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'strava_activity_id' not in data:
        return jsonify({'error': 'strava_activity_id is required'}), 400

    from services.race_report_service import RaceReportService
    service = RaceReportService()
    report = service.generate_report(plan_id, data['strava_activity_id'], user.id)

    if 'error' in report:
        return jsonify(report), 404

    return jsonify(report)


@bp.route('/<int:plan_id>/race-report', methods=['GET'])
@requires_premium('race_report')
def get_race_report(plan_id):
    """Get stored race report for a plan."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from services.race_report_service import RaceReportService
    service = RaceReportService()
    report = service.get_report(plan_id, user.id)

    if 'error' in report:
        return jsonify(report), 404

    return jsonify(report)


@bp.route('/templates', methods=['GET'])
def list_templates():
    """List available plan templates."""
    from services.plan_templates import get_templates
    return jsonify({'templates': get_templates()})


@bp.route('/pace-zones', methods=['GET'])
def get_pace_zones():
    """Get user's pace zones (auto-derived from flat pace + overrides)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from services.pace_zone_service import (
        compute_zones_by_method, flat_speed_to_pace, merge_zone_overrides,
        VALID_PACE_ZONE_METHODS,
    )

    params = learned_params_repo.find_one_by(user_id=user.id)

    v_flat = params.v_flat if params and hasattr(params, 'v_flat') else 3.33
    flat_pace = flat_speed_to_pace(v_flat)

    prefs = prefs_repo.get_by_user(user.id)
    # Explicit query params let the UI preview a method (and an unsaved race
    # result) before committing it. They override the stored preference.
    method = request.args.get('method') or (prefs.pace_zone_method if prefs else None) or 'physics'
    if method not in VALID_PACE_ZONE_METHODS:
        method = 'physics'

    def _query_float(key):
        raw = request.args.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    race_distance_m = _query_float('race_distance_m')
    race_time_s = _query_float('race_time_s')
    if race_distance_m is None and prefs:
        race_distance_m = prefs.pace_zone_race_distance_m
    if race_time_s is None and prefs:
        race_time_s = prefs.pace_zone_race_time_s

    result = compute_zones_by_method(
        method,
        v_flat_ms=v_flat,
        race_distance_m=race_distance_m,
        race_time_s=race_time_s,
    )

    # User overrides stored in user_learned_params.pace_zone_overrides (JSON field)
    overrides = getattr(params, 'pace_zone_overrides', None) if params else None
    zones = merge_zone_overrides(result['zones'], overrides)

    from services.pace_zone_service import compute_hr_zones, compute_power_zones
    hr = compute_hr_zones(
        hr_max=prefs.hr_max if prefs else None,
        hr_rest=prefs.hr_rest if prefs else None,
        lthr=prefs.lthr if prefs else None,
    )
    power = compute_power_zones(ftp_w=prefs.ftp_w if prefs else None)

    return jsonify({
        'flat_pace_min_per_km': round(flat_pace, 2),
        'v_flat_ms': round(v_flat, 2),
        'method': result['method'],
        'requested_method': method,
        'method_meta': result['meta'],
        'zones': zones,
        'has_overrides': overrides is not None and len(overrides or {}) > 0,
        'hr_zones': hr['zones'] if hr else None,
        'hr_basis': hr['basis'] if hr else None,
        'hr_inputs': hr['inputs'] if hr else None,
        'power_zones': power['zones'] if power else None,
        'ftp_w': power['inputs']['ftp_w'] if power else None,
    })


@bp.route('/pace-zones', methods=['PUT'])
def update_pace_zones():
    """Update user's pace zone overrides."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or 'zones' not in data:
        return jsonify({'error': 'zones field is required'}), 400
    if not isinstance(data['zones'], dict):
        return jsonify({'error': 'zones must be an object'}), 400

    from services.pace_zone_service import ZONE_ORDER
    from repositories import UserLearnedParamsRepository

    overrides = {}
    for zone_name, zone_data in data['zones'].items():
        if zone_name not in ZONE_ORDER:
            continue
        if not isinstance(zone_data, dict):
            return jsonify({'error': f'zone {zone_name} must be an object'}), 400
        override = {}
        try:
            if 'min_pace' in zone_data:
                override['min_pace'] = float(zone_data['min_pace'])
            if 'max_pace' in zone_data:
                override['max_pace'] = float(zone_data['max_pace'])
        except (TypeError, ValueError):
            return jsonify({'error': f'zone {zone_name} pace values must be numeric'}), 400
        if 'min_pace' in override and 'max_pace' in override and override['min_pace'] >= override['max_pace']:
            return jsonify({'error': f'zone {zone_name} min_pace must be less than max_pace'}), 400
        if override:
            overrides[zone_name] = override

    params_repo = UserLearnedParamsRepository()
    params = params_repo.find_one_by(user_id=user.id)
    if params:
        params.pace_zone_overrides = overrides if overrides else None
        params_repo.commit()
    else:
        return jsonify({'error': 'No learned params found. Upload activities first.'}), 404

    return jsonify({'status': 'updated', 'overrides': overrides})


@bp.route('/pace-zone-method', methods=['PUT'])
def update_pace_zone_method():
    """Persist the user's pace-zone derivation method + reference race.

    Direct REST surface so the settings UI isn't forced to go through the agent.
    Whitelisted to the pace-zone fields only.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from services.pace_zone_service import VALID_PACE_ZONE_METHODS

    data = request.get_json(silent=True) or {}
    method = data.get('method')
    if method not in VALID_PACE_ZONE_METHODS:
        return jsonify({'error': f'method must be one of {sorted(VALID_PACE_ZONE_METHODS)}'}), 400

    update = {'pace_zone_method': method}

    if method in ('vdot', 'riegel'):
        try:
            distance_m = float(data['race_distance_m'])
            time_s = float(data['race_time_s'])
        except (KeyError, TypeError, ValueError):
            return jsonify({
                'error': 'race_distance_m and race_time_s (numbers) are required for vdot/riegel',
            }), 400
        if distance_m <= 0 or time_s <= 0:
            return jsonify({'error': 'race_distance_m and race_time_s must be positive'}), 400
        update['pace_zone_race_distance_m'] = distance_m
        update['pace_zone_race_time_s'] = time_s
    else:
        # physics: clear any stale reference race so it can't resurface later.
        update['pace_zone_race_distance_m'] = None
        update['pace_zone_race_time_s'] = None

    prefs = prefs_repo.upsert(user.id, update)
    prefs_repo.commit()
    return jsonify({
        'status': 'updated',
        'pace_zone_method': prefs.pace_zone_method,
        'pace_zone_race_distance_m': prefs.pace_zone_race_distance_m,
        'pace_zone_race_time_s': prefs.pace_zone_race_time_s,
    })


# Allowed bpm ranges for each HR anchor; mirrors pace_zone_service validation.
_HR_FIELD_BOUNDS = {
    'hr_max': (100, 240),
    'hr_rest': (25, 120),
    'lthr': (80, 230),
}


@bp.route('/pace-zones/hr', methods=['PUT'])
def update_hr_anchors():
    """Persist the user's heart-rate anchors (hr_max / hr_rest / lthr).

    Each field is optional and may be set to null to clear it. Validated for
    physiological plausibility and internal consistency (rest < max, lthr <= max).
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    update = {}
    for field, (lo, hi) in _HR_FIELD_BOUNDS.items():
        if field not in data:
            continue
        raw = data[field]
        if raw is None:
            update[field] = None
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return jsonify({'error': f'{field} must be an integer bpm or null'}), 400
        if not (lo <= value <= hi):
            return jsonify({'error': f'{field} must be between {lo} and {hi} bpm'}), 400
        update[field] = value

    if not update:
        return jsonify({'error': 'provide at least one of hr_max, hr_rest, lthr'}), 400

    # Consistency checks use the post-update view (stored values + this request).
    prefs = prefs_repo.get_by_user(user.id)
    resolved = {
        f: update[f] if f in update else (getattr(prefs, f) if prefs else None)
        for f in _HR_FIELD_BOUNDS
    }
    if resolved['hr_max'] and resolved['hr_rest'] and resolved['hr_rest'] >= resolved['hr_max']:
        return jsonify({'error': 'hr_rest must be lower than hr_max'}), 400
    if resolved['hr_max'] and resolved['lthr'] and resolved['lthr'] > resolved['hr_max']:
        return jsonify({'error': 'lthr cannot exceed hr_max'}), 400

    prefs = prefs_repo.upsert(user.id, update)
    prefs_repo.commit()

    from services.pace_zone_service import compute_hr_zones
    hr = compute_hr_zones(prefs.hr_max, prefs.hr_rest, prefs.lthr)
    return jsonify({
        'status': 'updated',
        'hr_max': prefs.hr_max,
        'hr_rest': prefs.hr_rest,
        'lthr': prefs.lthr,
        'hr_basis': hr['basis'] if hr else None,
        'hr_zones': hr['zones'] if hr else None,
    })


@bp.route('/pace-zones/hr/autodetect', methods=['POST'])
def autodetect_hr_max():
    """Estimate HR-max from the user's recent Strava activity streams.

    Returns a suggestion only — it does not persist. The client confirms and
    PUTs it to ``/pace-zones/hr``. Scans the last ~6 months of activities that
    carry stream data.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from datetime import datetime, timedelta, timezone
    from services.pace_zone_service import estimate_hr_max_from_streams

    since = datetime.now(timezone.utc) - timedelta(days=183)
    activities = strava_activity_repo.get_activities_with_streams(user.id, after=since)
    estimate = estimate_hr_max_from_streams(a.streams for a in activities)

    if estimate is None:
        return jsonify({
            'hr_max_estimate': None,
            'activities_scanned': len(activities),
            'message': 'No heart-rate data found in recent activities.',
        })

    return jsonify({
        'hr_max_estimate': estimate,
        'activities_scanned': len(activities),
    })


# Allowed watt range for FTP; mirrors pace_zone_service validation.
_FTP_BOUNDS = (50, 600)


@bp.route('/pace-zones/power', methods=['PUT'])
def update_ftp():
    """Persist the user's running-power FTP (functional threshold power).

    ``ftp_w`` is optional and may be set to null to clear it. Validated for
    physiological plausibility (50-600 W).
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    if 'ftp_w' not in data:
        return jsonify({'error': 'ftp_w is required (integer watts or null)'}), 400

    raw = data['ftp_w']
    if raw is None:
        update = {'ftp_w': None}
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'ftp_w must be an integer watt value or null'}), 400
        lo, hi = _FTP_BOUNDS
        if not (lo <= value <= hi):
            return jsonify({'error': f'ftp_w must be between {lo} and {hi} W'}), 400
        update = {'ftp_w': value}

    prefs = prefs_repo.upsert(user.id, update)
    prefs_repo.commit()

    from services.pace_zone_service import compute_power_zones
    power = compute_power_zones(prefs.ftp_w)
    return jsonify({
        'status': 'updated',
        'ftp_w': prefs.ftp_w,
        'power_zones': power['zones'] if power else None,
    })


@bp.route('/pace-zones/power/autodetect', methods=['POST'])
def autodetect_ftp():
    """Estimate FTP from the user's recent Strava activity streams.

    Returns a suggestion only — it does not persist. The client confirms and
    PUTs it to ``/pace-zones/power``. Scans the last ~90 days of activities
    that carry power (watts) stream data; uses the best 20-min average × 0.95.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from datetime import datetime, timedelta, timezone
    from services.pace_zone_service import estimate_ftp_from_streams

    since = datetime.now(timezone.utc) - timedelta(days=90)
    activities = strava_activity_repo.get_activities_with_streams(user.id, after=since)
    estimate = estimate_ftp_from_streams(a.streams for a in activities)

    if estimate is None:
        return jsonify({
            'ftp_estimate': None,
            'activities_scanned': len(activities),
            'message': 'No usable power data found in recent activities.',
        })

    return jsonify({
        'ftp_estimate': estimate,
        'activities_scanned': len(activities),
    })


VALID_FEELINGS_API = {'great', 'good', 'ok', 'tired', 'bad'}


def _validate_checkin_payload(data: dict) -> tuple[dict, str | None]:
    """Validate and coerce a daily check-in payload. Returns (clean, error)."""
    if not isinstance(data, dict):
        return {}, 'payload must be an object'
    clean: dict = {}

    if 'rpe_yesterday' in data and data['rpe_yesterday'] is not None:
        try:
            val = int(data['rpe_yesterday'])
        except (TypeError, ValueError):
            return {}, 'rpe_yesterday must be an integer'
        if not 1 <= val <= 10:
            return {}, 'rpe_yesterday must be between 1 and 10'
        clean['rpe_yesterday'] = val

    if 'feeling' in data and data['feeling'] is not None:
        if data['feeling'] not in VALID_FEELINGS_API:
            return {}, f'feeling must be one of {sorted(VALID_FEELINGS_API)}'
        clean['feeling'] = data['feeling']

    if 'sleep_h' in data and data['sleep_h'] is not None:
        try:
            val = float(data['sleep_h'])
        except (TypeError, ValueError):
            return {}, 'sleep_h must be numeric'
        if not 0 <= val <= 24:
            return {}, 'sleep_h must be between 0 and 24'
        clean['sleep_h'] = val

    if 'soreness' in data and data['soreness'] is not None:
        try:
            val = int(data['soreness'])
        except (TypeError, ValueError):
            return {}, 'soreness must be an integer'
        if not 0 <= val <= 10:
            return {}, 'soreness must be between 0 and 10'
        clean['soreness'] = val

    if 'notes' in data and data['notes'] is not None:
        notes = str(data['notes'])
        if len(notes) > 2000:
            return {}, 'notes too long (max 2000 chars)'
        clean['notes'] = notes

    if not clean:
        return {}, 'no valid fields provided'
    return clean, None


@bp.route('/<int:plan_id>/checkin', methods=['POST'])
def post_daily_checkin(plan_id):
    """Submit today's check-in and apply readiness-driven adjustments.

    Body: {rpe_yesterday?: 1-10, feeling?: 'great|good|ok|tired|bad',
           sleep_h?: 0-24, soreness?: 0-10, notes?: string}

    The ``plan_id`` is used for authorization scoping (the caller must own a
    plan). The check-in itself is per-user-per-date; subsequent calls on the
    same day update the existing row. Returns the stored check-in plus any
    plan adjustments that were applied.
    """
    from datetime import datetime as _dt, timezone as _tz
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    data = request.get_json() or {}
    clean, err = _validate_checkin_payload(data)
    if err:
        return jsonify({'error': err}), 400

    today = _dt.now(_tz.utc).date()
    checkin = checkin_repo.upsert(user.id, today, clean)
    checkin_repo.commit()

    from services.plan_adjustment_service import PlanAdjustmentService
    adjustment_summary = PlanAdjustmentService().apply_for_user(user.id, today=today)

    return jsonify({
        'checkin': checkin.to_dict(),
        'adjustments': adjustment_summary,
    })


@bp.route('/<int:plan_id>/checkin', methods=['GET'])
def get_today_checkin(plan_id):
    """Return today's check-in for the requesting user (or null)."""
    from datetime import datetime as _dt, timezone as _tz
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    today = _dt.now(_tz.utc).date()
    checkin = checkin_repo.get_for_date(user.id, today)
    return jsonify({'checkin': checkin.to_dict() if checkin else None})


@bp.route('/<int:plan_id>/adjustments', methods=['GET'])
def get_plan_adjustments(plan_id):
    """Structured audit trail of automatic adjustments applied to a plan.

    GET /api/training-plan/<id>/adjustments?since=YYYY-MM-DD

    Returns the swap/downgrade history (most-recent first) so the UI can render
    an audit pane ("Wednesday's intervals were moved to Friday on May 21").
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    since = _iso_date_or_none(request.args.get('since'))
    if request.args.get('since') and since is None:
        return jsonify({'error': 'since must be YYYY-MM-DD'}), 400

    rows = adjustment_repo.list_for_plan(plan_id, user.id, since=since)
    return jsonify({'adjustments': [r.to_dict() for r in rows]})


@bp.route('/<int:plan_id>', methods=['DELETE'])
def delete_plan(plan_id):
    """Delete a training plan."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    plan = training_plan_repo.get_user_plan(plan_id, user.id)
    if not plan:
        return jsonify({'error': 'Plan not found'}), 404

    training_plan_repo.delete(plan)
    training_plan_repo.commit()
    return jsonify({'status': 'deleted', 'id': plan_id})


VALID_DAY_NAMES = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'}


@bp.route('/preferences', methods=['GET'])
def get_preferences():
    """Get user's training preferences."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    prefs = prefs_repo.get_by_user(user.id)
    if not prefs:
        return jsonify({'preferences': None})
    return jsonify({'preferences': prefs.to_dict()})


VALID_TERRAIN_PROFILES = {'flat_urban', 'rolling_hills', 'mountain'}

ALLOWED_PREFS_FIELDS = {
    'long_run_day', 'back_to_back', 'rest_days', 'mountain_days',
    'max_hours_per_day', 'strength_training_days', 'strength_preferred_days',
    'max_weekly_km', 'max_long_run_km', 'max_long_run_hours',
    'mountain_access_per_week', 'mountain_access_per_month',
    'max_mountain_elevation_m', 'max_mountain_distance_km',
    'sample_mountain_route_id', 'terrain_profile',
}

PREF_VALIDATORS = {
    'max_weekly_km':              lambda v: 0 < float(v) <= 200,
    'max_long_run_km':            lambda v: 0 < float(v) <= 80,
    'max_long_run_hours':         lambda v: 0 < float(v) <= 12,
    'mountain_access_per_week':   lambda v: 0 <= float(v) <= 7,
    'mountain_access_per_month':  lambda v: 0 <= int(v) <= 30,
    'max_mountain_elevation_m':   lambda v: 0 <= int(v) <= 5000,
    'max_mountain_distance_km':   lambda v: 0 < float(v) <= 60,
    'terrain_profile':            lambda v: v in VALID_TERRAIN_PROFILES,
}


@bp.route('/preferences', methods=['PUT'])
def update_preferences():
    """Create or update user's training preferences."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Validate day-name fields
    for field in ('rest_days', 'mountain_days', 'strength_preferred_days'):
        if field in data and data[field] is not None:
            if not isinstance(data[field], list):
                return jsonify({'error': f'{field} must be a list'}), 400
            invalid = [d for d in data[field] if d not in VALID_DAY_NAMES]
            if invalid:
                return jsonify({'error': f'Invalid day names in {field}: {invalid}'}), 400

    if 'long_run_day' in data and data['long_run_day'] is not None:
        if data['long_run_day'] not in VALID_DAY_NAMES:
            return jsonify({'error': f'Invalid long_run_day: {data["long_run_day"]}'}), 400

    if 'strength_training_days' in data and data['strength_training_days'] is not None:
        try:
            if not (0 <= int(data['strength_training_days']) <= 3):
                return jsonify({'error': 'strength_training_days must be 0-3'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'strength_training_days must be an integer'}), 400

    if 'max_hours_per_day' in data and data['max_hours_per_day'] is not None:
        try:
            if not (0.5 <= float(data['max_hours_per_day']) <= 12.0):
                return jsonify({'error': 'max_hours_per_day must be 0.5-12.0'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'max_hours_per_day must be numeric'}), 400

    # Range validation for new fields
    for field, validator in PREF_VALIDATORS.items():
        if field in data and data[field] is not None:
            try:
                if not validator(data[field]):
                    return jsonify({'error': f'{field} out of range or invalid'}), 400
            except (TypeError, ValueError):
                return jsonify({'error': f'{field} has wrong type'}), 400

    # Filter to known fields only
    clean = {k: v for k, v in data.items() if k in ALLOWED_PREFS_FIELDS}

    # Setting terrain_profile explicitly marks the source as user-confirmed.
    if 'terrain_profile' in clean:
        clean['terrain_profile_source'] = 'user'

    prefs = prefs_repo.upsert(user.id, clean)
    prefs_repo.commit()
    return jsonify({'preferences': prefs.to_dict()})


@bp.route('/terrain-profile/infer', methods=['GET'])
def infer_terrain_profile():
    """Infer terrain profile from the user's recent Strava activities."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    from services.terrain_profile_service import infer_user_terrain_profile

    try:
        lookback = int(request.args.get('lookback_days', 90))
    except ValueError:
        lookback = 90
    lookback = max(7, min(lookback, 365))

    return jsonify(infer_user_terrain_profile(user.id, lookback_days=lookback))

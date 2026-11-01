"""Single-workout tools: list_activities, get_activity_detail, compare_to_plan."""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import numpy as np
from flask import current_app

from config.hybrid_config import get_logger
from database import db
from models import Activity, User, WorkoutCompletion
from repositories import TrainingPlanRepository
from services import segment_match_service as sm
from services import workout_analysis_service as wa
from services.pace_zone_service import compute_hr_zones

logger = get_logger(__name__)

MAX_LIST = 100


def _parse_date(s: Optional[str], default: datetime) -> datetime:
    return datetime.fromisoformat(s[:10]) if s else default


def _get_activity(activity_id, user_id: int) -> Optional[Activity]:
    """Ownership-checked lookup: the row must belong to ``user_id``."""
    try:
        return Activity.query.filter_by(id=int(activity_id), user_id=user_id).first()
    except (TypeError, ValueError):
        return None


def _ensure_streams(act: Activity, user_id: int, need_latlng: bool = False) -> Optional[Dict]:
    """Stored streams, else fetch from Strava once and cache them on the row.

    need_latlng: also refetch when the stored streams predate the GPS track
    (rows saved before latlng was requested).
    """
    if wa.has_streams(act.streams) and (not need_latlng or sm.has_latlng(act.streams)):
        return act.streams
    if act.source != 'strava' or not act.strava_id:
        return act.streams if wa.has_streams(act.streams) else None
    from services.strava_service import StravaService
    user = db.session.get(User, user_id)
    svc = StravaService(current_app.config['STRAVA_CLIENT_ID'],
                        current_app.config['STRAVA_CLIENT_SECRET'],
                        current_app.config['STRAVA_REDIRECT_URI'])
    try:
        token, refresh, expires = svc.get_valid_token(user.access_token, user.refresh_token, user.expires_at)
        if token != user.access_token:
            user.access_token, user.refresh_token, user.expires_at = token, refresh, expires
            db.session.commit()
        streams = svc.download_streams(act.strava_id, token)
    except Exception as e:
        logger.warning(f"On-demand streams failed for activity {act.id}: {e}")
        return None
    if not wa.has_streams(streams):
        return act.streams if wa.has_streams(act.streams) else None
    act.streams = streams
    db.session.commit()
    return streams


def _user_zones(user_id: int, streams: Dict) -> Optional[Dict]:
    from services.intensity_service import profile_hr
    from services.intensity_service import hr_bounds
    hr_max, hr_rest = profile_hr(user_id)
    if not hr_max:
        # HR max across the user's recent runs, not this run's own peak (an easy run's
        # max would squeeze every zone down and make it read as tempo).
        recent = (Activity.query.filter(Activity.user_id == user_id, Activity._streams.isnot(None))
                  .order_by(Activity.start_date.desc()).limit(30).all())
        hr_max = hr_bounds(recent)[0]
    if not hr_max and streams.get('heartrate'):
        hr_max = int(max(streams['heartrate']))  # observed max in this run; a floor, not the true max
    z = compute_hr_zones(hr_max=hr_max, hr_rest=hr_rest)
    return z['zones'] if z else None


def _plan_day(act: Activity, user_id: int) -> Optional[Dict]:
    """Plan day for this activity: confirmed completion link, else same local date."""
    from services.plan_compliance_service import PlanComplianceService
    repo = TrainingPlanRepository()
    comp = WorkoutCompletion.query.filter_by(user_id=user_id, strava_activity_id=act.id).first()
    plans = repo.get_active_plans(user_id)
    if comp:
        plans = [p for p in [repo.get_user_plan(comp.plan_id, user_id)] if p]
    svc = PlanComplianceService()
    for plan in plans:
        start = svc._get_plan_start_date(plan)
        for week in plan.weeks or []:
            for day in week.get('days', []):
                wn = week.get('week_number', 1)
                if comp:
                    hit = (wn, day.get('day')) == (comp.week_number, comp.day)
                else:
                    hit = (day.get('workout_type') != 'rest'
                           and svc._get_workout_date(start, wn, day.get('day')) == act.local_date)
                if hit:
                    return {'plan_id': plan.id, 'plan_name': plan.plan_name, 'week': wn,
                            'day': day, 'compliance': comp.compliance_score if comp else None,
                            'status': comp.status if comp else None}
    return None


def _handle_list_activities(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    now = datetime.now()
    try:
        start = _parse_date(tool_input.get('start'), now - timedelta(days=14))
        end = _parse_date(tool_input.get('end'), now) + timedelta(days=1)
    except ValueError:
        return {'error': 'start/end must be YYYY-MM-DD'}
    q = Activity.query.filter(Activity.user_id == user_id, Activity.start_date >= start,
                              Activity.start_date < end)
    if tool_input.get('type'):
        q = q.filter(Activity.sport_type == tool_input['type'])
    acts = q.order_by(Activity.start_date.desc()).limit(MAX_LIST).all()
    comps = {c.strava_activity_id: c for c in WorkoutCompletion.query.filter(
        WorkoutCompletion.user_id == user_id,
        WorkoutCompletion.strava_activity_id.in_([a.id for a in acts])).all()} if acts else {}
    rows = []
    for a in acts:
        row = {'activity_id': a.id, 'date': a.local_date.isoformat(), 'name': a.name,
               'type': a.sport_type, 'distance_km': round((a.distance or 0) / 1000, 2),
               'elevation_gain_m': round(a.elevation_gain_m or 0), 'moving_time_s': a.moving_time_s,
               'is_race': bool(a.is_race), 'has_streams': wa.has_streams(a.streams)}
        s = a.streams if wa.has_streams(a.streams) else None
        if s and s.get('heartrate'):
            row['avg_hr'], row['max_hr'] = round(sum(s['heartrate']) / len(s['heartrate'])), max(s['heartrate'])
        c = comps.get(a.id)
        if c:
            row['plan_match'] = {'plan_id': c.plan_id, 'week': c.week_number, 'day': c.day,
                                 'workout_type': c.planned_workout_type, 'compliance': c.compliance_score}
        rows.append(row)
    return {'count': len(rows), 'truncated': len(rows) == MAX_LIST, 'activities': rows}


def _handle_get_activity_detail(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    act = _get_activity(tool_input.get('activity_id'), user_id)
    if not act:
        return {'error': 'Activity not found'}
    streams = _ensure_streams(act, user_id)
    head = {'activity_id': act.id, 'name': act.name, 'date': act.local_date.isoformat(),
            'distance_km': round((act.distance or 0) / 1000, 2), 'moving_time_s': act.moving_time_s,
            'elevation_gain_m': round(act.elevation_gain_m or 0)}
    if not streams:
        return {**head, 'error': 'No streams available for this activity (not on Strava or fetch failed).'}
    res = tool_input.get('resolution', 'km')
    if res not in ('km', 'lap', 'segment'):
        res = 'km'
    out = {**head, **wa.summarize(streams, res, _user_zones(user_id, streams))}
    if not out['altitude_available']:
        pd = _plan_day(act, user_id)
        km, elev = pd and pd['day'].get('distance_km'), pd and pd['day'].get('elevation_m')
        if pd and km and elev:
            out['planned_incline_pct'] = round(elev / (km * 10), 1)
            out['altitude_note'] += f" Matched plan day: {elev:.0f} m D+ over {km} km (~{out['planned_incline_pct']}% avg incline)."
    out['model_view'] = 'not included (use get_past_performance for predicted vs actual)'
    return out


def _handle_compare_to_plan(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    act = _get_activity(tool_input.get('activity_id'), user_id)
    if not act:
        return {'error': 'Activity not found'}
    pd = _plan_day(act, user_id)
    if not pd:
        return {'activity_id': act.id, 'matched': False, 'note': 'No planned workout on this date in an active plan.'}
    day = pd['day']
    streams = _ensure_streams(act, user_id)
    actual = {'distance_km': round((act.distance or 0) / 1000, 2),
              'elevation_m': round(act.elevation_gain_m or 0), 'duration_min': round((act.moving_time_s or 0) / 60)}
    planned = {k: day.get(k) for k in ('workout_type', 'title', 'distance_km', 'elevation_m', 'duration_min', 'notes')}
    steps = []
    if streams and day.get('steps'):
        steps = wa.step_targets(streams, day['steps'], _user_zones(user_id, streams))
    out = {'activity_id': act.id, 'matched': True, 'plan_id': pd['plan_id'], 'plan_name': pd['plan_name'], 'week': pd['week'],
           'day': day.get('day'), 'planned': planned, 'actual': actual, 'steps': steps,
           'compliance_score': pd['compliance'], 'verdict': wa.plan_verdict(planned, actual, steps)}
    if steps:
        out['steps_note'] = 'Steps aligned by cumulative planned duration/distance; approximate if the runner deviated.'
    if streams and not wa.altitude_usable(streams):
        out['treadmill'] = True
        out['verdict'] += '; altitude unavailable (treadmill), D+ actual is not reliable'
    return out


MAX_FETCH = 20          # Strava stream fetches per improvement call (rate limit: 100 / 15 min)
SEARCH_RADIUS_M = 20000  # candidate runs must start within this of the stretch start


def _handle_get_segment_improvement(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Same stretch in past runs: time, HR, metres per beat, improvement index."""
    from services.intensity_service import DEFAULT_HR_REST, profile_hr
    act = _get_activity(tool_input.get('activity_id'), user_id)
    if not act:
        return {'error': 'Activity not found'}
    streams = _ensure_streams(act, user_id, need_latlng=True)
    if not streams or not sm.has_latlng(streams):
        return {'error': 'No GPS track for this activity (treadmill, or not available from Strava).'}
    try:
        tol = min(100.0, max(15.0, float(tool_input.get('tolerance_m') or 30)))
        days = int(tool_input.get('period_days') or 365)
        a_km, b_km = tool_input.get('start_km'), tool_input.get('end_km')
        a_km, b_km = (float(a_km), float(b_km)) if a_km is not None and b_km is not None else (None, None)
    except (TypeError, ValueError):
        return {'error': 'start_km/end_km/tolerance_m/period_days must be numbers'}
    metric = 'time' if tool_input.get('metric') == 'time' else 'eff'
    if a_km is None:
        climbs = [c for c in wa.climbs_descents(streams) if c['type'] == 'climb']
        if not climbs:
            return {'error': 'No climb detected: pass start_km and end_km.'}
        big = max(climbs, key=lambda c: c['elev_m'])
        a_km, b_km = big['start_km'], big['start_km'] + big['length_m'] / 1000
    st = sm.stretch(streams, a_km * 1000, b_km * 1000)
    if not st:
        return {'error': 'Invalid stretch: end_km must be after start_km and inside the run.'}
    hr_rest = profile_hr(user_id)[1] or DEFAULT_HR_REST
    today = sm.pass_metrics(streams, st['lo'], st['hi'], hr_rest) or {}

    lat, lng = st['start']
    since = act.start_date - timedelta(days=days)
    cands = (Activity.query.filter(Activity.user_id == user_id, Activity.id != act.id,
                                   Activity.start_date < act.start_date, Activity.start_date >= since)
             .order_by(Activity.start_date.desc()).all())
    past, fetched, pending, checked = [], 0, 0, 0
    for c in cands:
        if c.start_lat is not None and c.start_lng is not None and \
                sm._dist_m(np.array([[c.start_lat, c.start_lng]]), lat, lng)[0] > SEARCH_RADIUS_M:
            continue
        s = c.streams
        if not sm.has_latlng(s):
            if c.source != 'strava' or not c.strava_id:
                continue
            if fetched >= MAX_FETCH:
                pending += 1
                continue
            fetched += 1
            s = _ensure_streams(c, user_id, need_latlng=True)
            if not sm.has_latlng(s):
                continue
        checked += 1
        hit = sm.find_pass(s, st, tol)
        if hit:
            m = sm.pass_metrics(s, *hit, hr_rest)
            if m:
                past.append({'activity_id': c.id, 'date': c.local_date.isoformat(), 'name': c.name, **m})
    idx = sm.improvement(today, past, metric)
    past.sort(key=lambda p: p['date'])
    return {'activity_id': act.id, 'date': act.local_date.isoformat(),
            'stretch': {'start_km': round(a_km, 2), 'end_km': round(b_km, 2),
                        'length_m': round(st['length_m'])},
            'settings': {'metric': metric, 'tolerance_m': tol, 'period_days': days, 'hr_rest': hr_rest},
            'today': today, 'past': past, **idx,
            'checked_runs': checked, 'pending_runs': pending,
            'note': ('m_per_beat = grade-adjusted metres per minute / beats above rest. '
                     + (f'{pending} older runs still lack a GPS track; call again to check more.' if pending else ''))}


def analysis_profile(streams: Dict, step_m: float = 100.0) -> list:
    """[[distance_m, altitude, hr, speed]] every ``step_m`` for the site's chart."""
    d = streams.get('distance') or []
    out, nxt = [], 0.0
    for i, x in enumerate(d):
        if x >= nxt:
            out.append([round(x), *(round(streams[k][i], 1) if len(streams.get(k) or []) == len(d) else None
                                    for k in ('altitude', 'heartrate', 'velocity_smooth'))])
            nxt += step_m
    return out

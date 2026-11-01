"""Race calendar API — browse, filter, view details.

Read endpoints are public (no auth) so the marketing pages can preview
the calendar. Write endpoints (e.g. add-to-plan, in step 5) require a
JWT.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from flask import Blueprint, Response, current_app, jsonify, request

from api.utils import get_current_user
from database import db
from models.training_plan import TrainingPlan
from repositories.race_repository import RaceRepository
from repositories.training_plan_repository import TrainingPlanRepository
from repositories.user_training_preferences_repository import (
    UserTrainingPreferencesRepository,
)
from services.plan_readiness import (
    assess_readiness,
    get_athlete_baseline,
    suggest_alternative_races,
    weeks_until,
)
from services.race_calendar_service import _haversine_km, _score_race

bp = Blueprint('races', __name__, url_prefix='/api/races')
race_repo = RaceRepository()
plan_repo = TrainingPlanRepository()
prefs_repo = UserTrainingPreferencesRepository()


# Default plan length per priority (weeks). Tunable; the agent can later
# override via generate_full_plan with a different length.
DEFAULT_PLAN_WEEKS = {'A': 12, 'B': 6, 'C': 3}
VALID_PRIORITIES = {'A', 'B', 'C'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_float(name: str) -> Optional[float]:
    raw = request.args.get(name)
    if raw is None or raw == '':
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(name: str) -> Optional[int]:
    raw = request.args.get(name)
    if raw is None or raw == '':
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_date(name: str):
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _decorate_with_distance(items, *, near_lat, near_lon, target_distance_km, target_elev_m, radius_km):
    """Attach distance_from_base_km + fit_score when "near me" is in play."""
    out = []
    for r in items:
        d = {
            **r.to_summary(),
            'url': r.url,
        }
        if near_lat is not None and near_lon is not None:
            d_km = _haversine_km(near_lat, near_lon, r.lat, r.lon)
            d['distance_from_base_km'] = round(d_km, 1) if d_km is not None else None
            if target_distance_km is not None and d_km is not None:
                d['fit_score'] = _score_race(
                    {
                        'distance_km': r.distance_km,
                        'elev_m': r.elev_gain_m or 0,
                        'distance_from_base_km': d_km,
                    },
                    target_distance_km=target_distance_km,
                    target_elev_m=target_elev_m,
                    radius_km=radius_km or 100.0,
                )
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
def list_races():
    """Browse the calendar with filters.

    Query params:
        q, start_date, end_date, country,
        min_distance_km, max_distance_km,
        min_elev_m, max_elev_m,
        surface, race_type,
        near_lat, near_lon, max_travel_km,
        target_distance_km, target_elev_m,
        sort (date|distance|fit_score), limit (<=100), offset
    """
    near_lat = _parse_float('near_lat')
    near_lon = _parse_float('near_lon')
    max_travel_km = _parse_float('max_travel_km')
    target_distance_km = _parse_float('target_distance_km')
    target_elev_m = _parse_float('target_elev_m')
    sort = request.args.get('sort') or 'date'
    limit = _parse_int('limit') or 50
    offset = _parse_int('offset') or 0

    start_date = _parse_date('start_date')
    if start_date is None and 'start_date' not in request.args:
        start_date = date.today()

    filters: Dict[str, Any] = dict(
        q=request.args.get('q'),
        start_date=start_date,
        end_date=_parse_date('end_date'),
        country=request.args.get('country'),
        min_distance_km=_parse_float('min_distance_km'),
        max_distance_km=_parse_float('max_distance_km'),
        min_elev_m=_parse_float('min_elev_m'),
        max_elev_m=_parse_float('max_elev_m'),
        surface=request.args.get('surface'),
        race_type=request.args.get('race_type'),
        near_lat=near_lat,
        near_lon=near_lon,
        max_travel_km=max_travel_km,
    )

    db_sort = 'date' if sort == 'fit_score' else sort
    rows = race_repo.search(
        sort=db_sort,
        limit=limit if sort != 'fit_score' else min(limit * 4, 200),
        offset=offset,
        **filters,
    )

    decorated = _decorate_with_distance(
        rows,
        near_lat=near_lat,
        near_lon=near_lon,
        target_distance_km=target_distance_km,
        target_elev_m=target_elev_m,
        radius_km=max_travel_km or 100.0,
    )

    if sort == 'fit_score':
        decorated.sort(
            key=lambda x: x.get('fit_score') or -1,
            reverse=True,
        )
        decorated = decorated[:limit]

    return jsonify({
        'races': decorated,
        'limit': limit,
        'offset': offset,
        'sort': sort,
    })


@bp.route('/<int:race_id>', methods=['GET'])
def get_race(race_id: int):
    """Race detail. Public."""
    race = race_repo.get_by_id(race_id)
    if not race:
        return jsonify({'error': 'Race not found'}), 404
    return jsonify({'race': race.to_dict()})


@bp.route('/by-slug/<slug>', methods=['GET'])
def get_race_by_slug(slug: str):
    """Race detail by slug — useful for SEO-friendly URLs."""
    race = race_repo.get_by_slug(slug)
    if not race:
        return jsonify({'error': 'Race not found'}), 404
    return jsonify({'race': race.to_dict()})


@bp.route('/discover', methods=['POST'])
def discover():
    """Search the web for a race not in the calendar and add it. Auth.

    Body: {"q": "Penna Trail Molina di Quosa"} -> {"races": [...]} (one per course).
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    q = ((request.get_json(silent=True) or {}).get('q') or '').strip()
    if len(q) < 3:
        return jsonify({'error': 'q is required'}), 400
    from services.race_discovery_service import discover_race
    try:
        races = discover_race(q)
    except Exception:
        current_app.logger.exception('race discovery failed for %r', q)
        return jsonify({'error': 'Online search failed, try again later'}), 502
    return jsonify({'races': [r.to_dict() for r in races]})


@bp.route('/<int:race_id>/poster', methods=['GET'])
def race_poster(race_id: int):
    race = race_repo.get_by_id(race_id)
    if not race or not race.poster_mime:
        return jsonify({'error': 'No poster'}), 404
    return Response(race.poster_data, mimetype=race.poster_mime,
                    headers={'Cache-Control': 'public, max-age=86400'})


@bp.route('/<int:race_id>/gpx', methods=['GET'])
def race_gpx(race_id: int):
    race = race_repo.get_by_id(race_id)
    if not race or not race.has_gpx:
        return jsonify({'error': 'No GPX'}), 404
    return Response(race.gpx_data, mimetype='application/gpx+xml',
                    headers={'Content-Disposition': f'attachment; filename="{race.slug}.gpx"'})


def _readiness_inputs(user, race):
    """Pull baseline + prefs for the readiness gate.

    Strava-derived longest run wins; user prefs ``max_long_run_km`` is
    the fallback. ``None`` means we can't tell — readiness skips the
    long-run gate but still enforces the time-window gate.
    """
    baseline = get_athlete_baseline(user.id)
    longest_run_km = baseline.get('longest_run_km')

    prefs_obj = prefs_repo.get_by_user(user.id)
    prefs = prefs_obj.to_dict() if prefs_obj else {}

    if not longest_run_km and prefs.get('max_long_run_km'):
        longest_run_km = float(prefs['max_long_run_km'])
        baseline['source'] = (baseline.get('source') or 'none') + '+prefs_cap'

    return baseline, prefs, longest_run_km


@bp.route('/<int:race_id>/plan', methods=['POST'])
def add_race_to_plan(race_id: int):
    """Create a stub TrainingPlan that targets ``race_id`` with the given
    priority. Idempotent on (user, race_id): a second call returns the
    existing plan instead of creating a duplicate. Auth required.

    Body: {"priority": "A"|"B"|"C", "weeks": int (optional),
           "force": bool (optional, override an ``unrealistic`` verdict)}

    Refuses (HTTP 409) when the readiness assessment marks the request
    ``unrealistic`` unless ``force=true`` is set; the response body
    carries the verdict and a list of safer alternative races.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    priority = (payload.get('priority') or '').upper()
    if priority not in VALID_PRIORITIES:
        return jsonify({'error': 'priority must be one of A, B, C'}), 400

    race = race_repo.get_by_id(race_id)
    if not race:
        return jsonify({'error': 'Race not found'}), 404

    existing = plan_repo.find_one_by(user_id=user.id, race_id=race.id)
    if existing:
        # Idempotent: just bump the priority if the user changed their mind.
        if existing.race_priority != priority:
            existing.race_priority = priority
            db.session.commit()
        return jsonify({'plan': existing.to_dict(), 'created': False})

    weeks_count = payload.get('weeks')
    if not isinstance(weeks_count, int) or weeks_count <= 0:
        weeks_count = DEFAULT_PLAN_WEEKS[priority]

    # ---- Readiness gate -----------------------------------------------------
    baseline, prefs, longest_run_km = _readiness_inputs(user, race)
    available_weeks = min(weeks_count, weeks_until(race.date)) if race.date else weeks_count

    verdict = assess_readiness(
        race_distance_km=race.distance_km or 0,
        available_weeks=available_weeks,
        athlete_longest_run_km=longest_run_km or 0.0,
        athlete_weekly_km=baseline.get('weekly_km') or 0.0,
        ctl=baseline.get('ctl'),
    )

    force = bool(payload.get('force'))
    if verdict.status == 'unrealistic' and not force:
        alternatives = suggest_alternative_races(
            race_distance_km=race.distance_km or 0,
            athlete_longest_run_km=longest_run_km or 0.0,
            after_date=race.date,
            near_lat=user.training_base_lat,
            near_lon=user.training_base_lon,
            max_travel_km=user.training_travel_radius_km,
        )
        return jsonify({
            'error': 'race_not_feasible',
            'verdict': verdict.to_dict(),
            'baseline': baseline,
            'alternatives': alternatives,
            'hint': (
                "Il piano è stato rifiutato perché la gara è troppo "
                "impegnativa rispetto al tuo livello attuale. Puoi (a) "
                "scegliere una gara più corta tra le alternative, (b) "
                "spostare l'obiettivo in avanti per avere più settimane, "
                "o (c) ripetere la richiesta con \"force\": true per "
                "procedere comunque (rischio infortuni)."
            ),
        }), 409

    race_dt = datetime.combine(race.date, datetime.min.time())
    plan = TrainingPlan(
        user_id=user.id,
        race_id=race.id,
        plan_name=race.name,
        race_date=race_dt,
        race_description=race.description,
        race_priority=priority,
        # Empty weeks scaffold — the agent / plan engine fills it on demand.
        weeks=[{'week_number': i + 1, 'days': []} for i in range(weeks_count)],
        status='draft',
    )
    plan_repo.save(plan)
    db.session.commit()

    response = {
        'plan': plan.to_dict(),
        'created': True,
        'verdict': verdict.to_dict(),
    }
    if force and verdict.status == 'unrealistic':
        response['forced'] = True
    return jsonify(response), 201


@bp.route('/me/preferences', methods=['GET'])
def my_preferences():
    """Returns the authenticated user's training-base hints so the frontend
    can pre-fill 'near me' filters. 401 if not logged in.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({
        'training_base_lat': user.training_base_lat,
        'training_base_lon': user.training_base_lon,
        'training_base_name': user.training_base_name,
        'training_travel_radius_km': user.training_travel_radius_km,
    })

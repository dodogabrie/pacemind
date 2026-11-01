"""Match abstract plan workouts to the user's saved TrainingRoute library.

The plan engine produces target distance/elevation per day; this service finds
the best real route for each workout (or flags it as ``unmatched`` so the
agent/UI can offer alternatives: generate, upload, downgrade).

The plan engine does NOT import this module — orchestration lives in
``plan_orchestrator`` to keep the engine free of repository dependencies.
"""

from __future__ import annotations

# Workout types whose primary intent is climbing.
_MOUNTAIN_WORKOUTS = ('hill_repeats', 'vert_session')

# Tolerance bands (km_pct, elev_low_pct, elev_high_pct, elev_abs_extra)
# elev_abs_extra: maximum absolute elevation extra (meters) for non-percentage fallbacks.
_TOLERANCES = {
    'long_run':       {'km': 0.20, 'elev_low': 0.30, 'elev_high': 0.30},
    'hill_repeats':   {'km': 0.25, 'elev_low': 0.20, 'elev_high': 0.40},
    'vert_session':   {'km': 0.25, 'elev_low': 0.10, 'elev_high': 0.50},
    'intervals':      {'km': 0.25, 'elev_abs': 100},
    'tempo':          {'km': 0.25, 'elev_low': 0.50, 'elev_high': 0.50, 'elev_abs': 150},
    'easy':           {'km': 0.30, 'elev_abs': 100},
    'recovery':       {'km': 0.30, 'elev_abs': 100},
}

_DEFAULT_TOL = {'km': 0.30, 'elev_abs': 100}


def _tol_for(workout_type: str) -> dict:
    return _TOLERANCES.get(workout_type, _DEFAULT_TOL)


def _within_km_tolerance(target_km: float, route_km: float, tol: dict) -> bool:
    if target_km <= 0:
        return True
    return abs(route_km - target_km) / max(target_km, 1.0) <= tol.get('km', 0.30)


def _within_elev_tolerance(target_elev: float, route_elev: float, tol: dict) -> bool:
    if target_elev <= 0:
        # Flat workouts: cap absolute elevation
        return route_elev <= tol.get('elev_abs', 100)
    if 'elev_abs' in tol and 'elev_low' not in tol:
        return abs(route_elev - target_elev) <= tol['elev_abs']
    elev_low = tol.get('elev_low', 0.30)
    elev_high = tol.get('elev_high', 0.30)
    if route_elev < target_elev * (1.0 - elev_low):
        return False
    if route_elev > target_elev * (1.0 + elev_high):
        return False
    return True


def _score(target_km: float, target_elev: float,
           route_km: float, route_elev: float,
           required_tags: list[str] | None,
           route_tags: list[str] | None) -> float:
    km_score = abs(route_km - target_km) / max(1.0, target_km)
    if target_elev > 0:
        elev_score = abs(route_elev - target_elev) / max(1.0, target_elev)
    else:
        elev_score = min(1.0, route_elev / 100.0)
    tag_mismatch = 0.0
    if required_tags:
        rt = set(route_tags or [])
        if not any(t in rt for t in required_tags):
            tag_mismatch = 1.0
    return 0.5 * km_score + 0.4 * elev_score + 0.1 * tag_mismatch


_DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _km_between(lat1, lon1, lat2, lon2) -> float:
    from math import cos, hypot, radians
    return hypot((lat2 - lat1) * 111.0, (lon2 - lon1) * 111.0 * cos(radians(lat1)))


def resolve_day_location(day: dict, locations: list):
    """Location for a plan day: its own override, else the one owning its weekday.

    Treadmill days have none. Returns a TrainingLocation or None (callers then
    fall back to the user's training base).
    """
    if day.get('treadmill'):
        return None
    if day.get('location_id'):
        found = next((l for l in locations if l.id == day['location_id']), None)
        if found:
            return found
    wd = _DAY_NAMES.index(day['day']) if day.get('day') in _DAY_NAMES else None
    return next((l for l in locations if wd is not None and wd in (l.weekdays or [])), None)


def _near(routes: list, location) -> list:
    """Routes whose center lies within the location radius (centerless ones are kept)."""
    return [r for r in routes
            if r.center_lat is None or r.center_lon is None
            or _km_between(location.lat, location.lon, r.center_lat, r.center_lon) <= location.radius_km]


def match_route_for_workout(
    user_id: int,
    workout_type: str,
    target_km: float,
    target_elev: float,
    *,
    terrain_profile: str | None = None,
    terrain_tags: list[str] | None = None,
    routes=None,
    location=None,
):
    """Pick the best TrainingRoute for an abstract workout.

    With ``location`` only routes centered within its radius are considered.

    Returns:
        (route_or_None, quality) where quality is 'exact' | 'approx' | 'unmatched'.
    """
    if routes is None:
        from repositories import TrainingRouteRepository
        routes = TrainingRouteRepository().get_user_routes(user_id)

    if routes and location is not None:
        routes = _near(routes, location)
    if not routes:
        return None, 'unmatched'

    tol = _tol_for(workout_type)
    is_mountain = workout_type in _MOUNTAIN_WORKOUTS

    candidates = []
    for r in routes:
        rk = float(r.distance_km or 0)
        re = float(r.elevation_gain_m or 0)

        # Hard filters
        if is_mountain and re < 0.7 * max(target_elev, 1):
            continue
        if (not is_mountain and terrain_profile == 'flat_urban'
                and rk > 0 and (re / rk) > 25):
            continue
        if not _within_km_tolerance(target_km, rk, tol):
            continue
        if not _within_elev_tolerance(target_elev, re, tol):
            continue

        score = _score(target_km, target_elev, rk, re,
                       terrain_tags, getattr(r, 'tags', None))
        candidates.append((score, r))

    # Long-run rescue: if none in tolerance for a long run, allow the longest route as approx.
    if not candidates and workout_type == 'long_run' and target_km > 25:
        longest = max(routes, key=lambda r: float(r.distance_km or 0))
        if longest.distance_km and longest.distance_km >= target_km * 0.7:
            return longest, 'approx'

    if not candidates:
        return None, 'unmatched'

    candidates.sort(key=lambda x: x[0])
    best_score, best_route = candidates[0]

    if best_score < 0.10:
        return best_route, 'exact'
    if best_score < 0.25:
        return best_route, 'approx'
    return None, 'unmatched'


def _suggested_alternatives(workout_type: str,
                            target_km: float,
                            target_elev: float,
                            available_routes: list) -> list[dict]:
    """Build the standard alternative-action menu for an unmatched workout."""
    # Closest route (any) for the downgrade fallback.
    downgrade = None
    if available_routes:
        downgrade = min(
            available_routes,
            key=lambda r: abs((r.distance_km or 0) - target_km)
                          + abs((r.elevation_gain_m or 0) - target_elev) / max(50, target_elev or 50),
        )

    alternatives = [
        {
            'action': 'generate',
            'description': (
                f"Genera percorso da training base "
                f"(~{target_km:.1f}km, {int(target_elev)}m D+)"
            ),
            'tool': 'generate_training_route',
            'params': {
                'distance_km': round(target_km, 1),
                'elevation_gain_m': int(target_elev),
            },
        },
        {
            'action': 'upload',
            'description': "Carica un GPX simile dai tuoi archivi",
        },
    ]
    if downgrade is not None:
        alternatives.append({
            'action': 'downgrade',
            'description': (
                f"Riduci a {downgrade.distance_km:.1f}km / "
                f"{int(downgrade.elevation_gain_m or 0)}m D+ "
                f"(percorso esistente: {downgrade.name})"
            ),
            'fallback_route_id': downgrade.id,
            'fallback_target': {
                'distance_km': float(downgrade.distance_km or 0),
                'elevation_m': float(downgrade.elevation_gain_m or 0),
            },
        })
    return alternatives


_MAX_GENERATIONS = 3  # ORS calls per match_routes_to_plan


def _generate_route(user_id: int, wt: str, target_km: float, target_elev: float, origin=None):
    """Best-effort ORS loop near ``origin`` (a TrainingLocation) or the training base, saved as source='generated'."""
    try:
        from models import User
        from models.training_route import TrainingRoute
        from repositories import TrainingRouteRepository
        from services.route_generation_service import RouteGenerationService

        svc = RouteGenerationService()
        if not svc.api_key:
            return None
        user = User.query.get(user_id)
        lat, lon = getattr(user, 'training_base_lat', None), getattr(user, 'training_base_lon', None)
        if origin is not None:
            lat, lon = origin.lat, origin.lon
        if lat is None or lon is None:
            base = svc.infer_training_base(user_id)
            if not base:
                return None
            lat, lon = base['lat'], base['lon']
        res = svc.generate_loop_route(
            center_lat=lat, center_lon=lon, target_distance_km=target_km,
            target_elevation_m=target_elev or None,
        )
        if 'error' in res:
            return None
        route = TrainingRoute(
            user_id=user_id, name=f"Generated {target_km:.0f}km loop", source='generated',
            route_data=res['route_data'], distance_km=res['distance_km'],
            elevation_gain_m=res['elevation_gain_m'], elevation_loss_m=res['elevation_loss_m'],
            center_lat=round(lat, 6), center_lon=round(lon, 6),
            generation_params={'center_lat': lat, 'center_lon': lon,
                               'target_distance_km': target_km, 'target_elevation_m': target_elev},
        )
        TrainingRouteRepository().create(route)
        return route
    except Exception:
        return None


def match_routes_to_plan(plan, prefs) -> dict:
    """Attach route_id + match quality to every running day in ``plan.weeks``.

    Mutates ``plan.weeks`` in-place.

    Args:
        plan: TrainingPlan instance (or any object with a mutable ``weeks`` list).
        prefs: UserTrainingPreferences instance or dict.

    Returns:
        {matched, approx, unmatched, unmatched_workouts: [...]}
    """
    from repositories import TrainingRouteRepository

    user_id = getattr(plan, 'user_id', None)
    if user_id is None:
        return {'matched': 0, 'approx': 0, 'unmatched': 0, 'unmatched_workouts': []}

    routes = TrainingRouteRepository().get_user_routes(user_id)
    if not routes:
        try:
            from services.route_suggestion_service import sync_frequent_routes
            if sync_frequent_routes(user_id):
                routes = TrainingRouteRepository().get_user_routes(user_id)
        except Exception:
            pass  # best-effort: matching proceeds with no routes

    from repositories import TrainingLocationRepository
    locations = TrainingLocationRepository().get_user_locations(user_id)

    prefs_dict = prefs.to_dict() if hasattr(prefs, 'to_dict') else (prefs or {})
    terrain_profile = prefs_dict.get('terrain_profile')

    summary = {'matched': 0, 'approx': 0, 'unmatched': 0, 'unmatched_workouts': []}
    generated = []  # routes made in this call, reusable by similar days
    attempts = 0

    weeks = plan.weeks or []
    for week in weeks:
        week_no = week.get('week_number') or week.get('week') or 0
        for day in week.get('days', []):
            wt = day.get('workout_type')
            if not wt or wt in ('rest', 'cross_training', 'strength'):
                continue
            target_km = float(day.get('distance_km') or 0)
            target_elev = float(day.get('elevation_m') or 0)
            if target_km <= 0:
                continue

            loc = resolve_day_location(day, locations)
            day['resolved_location_id'] = loc.id if loc else None
            route, quality = match_route_for_workout(
                user_id, wt, target_km, target_elev,
                terrain_profile=terrain_profile,
                routes=routes,
                location=loc,
            )

            if route is None and not day.get('treadmill'):
                tol = _tol_for(wt)
                route = next((g for g in generated
                              if (loc is None or _near([g], loc))
                              and _within_km_tolerance(target_km, g.distance_km, tol)
                              and _within_elev_tolerance(target_elev, g.elevation_gain_m or 0, tol)),
                             None)
                if route is None and attempts < _MAX_GENERATIONS:
                    attempts += 1
                    route = _generate_route(user_id, wt, target_km, target_elev, loc)
                    if route is not None:
                        generated.append(route)
                if route is not None:
                    quality = 'generated'

            if route is not None:
                day['route_id'] = route.id
                day['route_match_quality'] = quality
                day['suggested_alternatives'] = []
                summary['matched' if quality == 'exact' else 'approx'] += 1  # generated counts as approx
            else:
                day['route_id'] = None
                day['route_match_quality'] = 'unmatched'
                day['suggested_alternatives'] = _suggested_alternatives(
                    wt, target_km, target_elev, routes,
                )
                summary['unmatched'] += 1
                summary['unmatched_workouts'].append({
                    'week': week_no,
                    'day': day.get('day'),
                    'workout_type': wt,
                    'target_km': target_km,
                    'target_elev': target_elev,
                })

    return summary


def set_day_location(plan, week_number: int, day_name: str, location_id, prefs=None):
    """Set (or clear, with None) a plan day's location override and re-match its route.

    Returns the updated day dict, or None when the week/day does not exist.
    Raises ValueError if ``location_id`` is not one of the user's locations.
    """
    import copy
    from repositories import TrainingLocationRepository
    if location_id is not None and not TrainingLocationRepository().get_user_location(location_id, plan.user_id):
        raise ValueError('Location not found')
    weeks = copy.deepcopy(plan.weeks or [])
    week = next((w for w in weeks if w.get('week_number') == week_number), None)
    day = next((d for d in (week or {}).get('days', []) if d.get('day') == day_name), None)
    if day is None:
        return None
    day['location_id'] = location_id
    proxy = type('_Proxy', (), {})()
    proxy.user_id, proxy.weeks = plan.user_id, [{'days': [day]}]
    match_routes_to_plan(proxy, prefs)
    plan.weeks = weeks
    return day


def rematch_day_if_changed(user_id: int, day: dict, before: dict, prefs=None) -> None:
    """Re-match a day's route when an edit changed what the route depends on. Best-effort."""
    keys = ('workout_type', 'distance_km', 'elevation_m', 'treadmill')
    if all(before.get(k) == day.get(k) for k in keys):
        return
    try:
        proxy = type('_Proxy', (), {})()
        proxy.user_id, proxy.weeks = user_id, [{'days': [day]}]
        match_routes_to_plan(proxy, prefs)
    except Exception:
        pass


def rematch_stale_days(user_id: int, days: list, prefs=None) -> int:
    """Re-match the days (mutated in place) whose resolved location no longer matches.

    Skips days with an explicit ``location_id`` override and treadmill/non-run days;
    returns how many were re-matched. One ORS budget (max 3) is shared by the batch.
    """
    from repositories import TrainingLocationRepository
    locations = TrainingLocationRepository().get_user_locations(user_id)
    stale = []
    for d in days:
        if d.get('location_id') or d.get('treadmill') or not d.get('workout_type') or float(d.get('distance_km') or 0) <= 0:
            continue
        loc = resolve_day_location(d, locations)
        if (loc.id if loc else None) != d.get('resolved_location_id'):
            stale.append(d)
    if stale:
        proxy = type('_Proxy', (), {})()
        proxy.user_id, proxy.weeks = user_id, [{'days': stale}]
        match_routes_to_plan(proxy, prefs)
    return len(stale)


def rematch_future_plan_days(user_id: int, prefs=None) -> int:
    """After a weekday change: re-match future days of the user's active/draft plans (#121)."""
    import copy
    from datetime import date
    from models.training_plan import TrainingPlan
    from services.plan_adjustment_service import PlanAdjustmentService as P
    today, total = date.today(), 0
    for plan in TrainingPlan.query.filter(TrainingPlan.user_id == user_id,
                                          TrainingPlan.status.in_(('active', 'draft'))):
        weeks, start = copy.deepcopy(plan.weeks or []), P._plan_start(plan)
        future = [d for w in weeks for d in (w.get('days') or [])
                  if (dt := P._day_calendar_date(w, d, start)) and dt > today]
        n = rematch_stale_days(user_id, future, prefs)
        if n:
            plan.weeks, total = weeks, total + n
    return total

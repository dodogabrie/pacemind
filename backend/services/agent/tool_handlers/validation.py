"""Validation helpers, constants, and coaching knowledge checks.

Shared across multiple handler modules — import from here to avoid duplication.
"""

from typing import Dict
from datetime import datetime, timedelta, timezone

from config.hybrid_config import get_logger
from repositories import UserLearnedParamsRepository, GPXFileRepository

logger = get_logger(__name__)


# ============================================================================
# Training Plan Constants
# ============================================================================

VALID_WORKOUT_TYPES = {'easy', 'tempo', 'intervals', 'long_run', 'hill_repeats', 'rest', 'cross_train', 'recovery', 'vert_session', 'back_to_back', 'race_simulation', 'strength'}
VALID_DAYS = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'}
VALID_INTENSITIES = {'easy', 'moderate', 'hard', 'race_pace'}
MAX_SINGLE_RUN_KM = 60
MAX_WEEKLY_KM = 200

_RECOVERY_THEMES = {'recovery', 'taper', 'rest', 'deload'}
_SPEED_WORKOUT_TYPES = {'intervals', 'hill_repeats', 'tempo'}
_HIGH_INTENSITY_TYPES = {'intervals', 'hill_repeats', 'race_simulation'}
_KEY_WORKOUT_TYPES = {'long_run', 'intervals', 'hill_repeats', 'tempo',
                      'race_simulation', 'vert_session', 'back_to_back'}
_HIGH_IMPACT_TYPES = {'long_run', 'intervals', 'hill_repeats'}

# Z3+ workout types that require aerobic base readiness
_Z3_PLUS_WORKOUT_TYPES = {'intervals', 'tempo', 'hill_repeats'}

# Day ordering for back-to-back validation
_DAY_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

_DAY_OFFSETS = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
                'Friday': 4, 'Saturday': 5, 'Sunday': 6}

_DAY_NAMES = {v: k for k, v in _DAY_OFFSETS.items()}

# --- Timeline Reasonableness Check ---

# Minimum weeks by race distance (book-sourced absolute minimums)
_RACE_MINIMUM_WEEKS = [
    (21, 6),     # Half-marathon trail
    (30, 8),     # 30K trail
    (42, 10),    # Trail marathon
    (50, 12),    # 50K
    (80, 16),    # 50 miles
    (100, 18),   # 100K
    (160, 22),   # 100 miles
]

# Recommended peak weekly volume ranges by race distance (km/week)
_RACE_PEAK_VOLUME = [
    (21, (40, 50)),
    (30, (50, 60)),
    (42, (55, 70)),
    (50, (65, 90)),
    (80, (90, 130)),
    (100, (100, 140)),
    (160, (115, 160)),
]


# ============================================================================
# Annotation Constants
# ============================================================================

VALID_WAYPOINT_TYPES = {'aid_station', 'generic', 'water', 'checkpoint', 'caution'}

DEFAULT_STOP_TIMES = {
    'aid_station': 60,
    'water': 30,
    'checkpoint': 0,
    'caution': 0,
    'generic': 0,
}


# ============================================================================
# Helper Functions
# ============================================================================

def _is_recovery_week(theme: str) -> bool:
    """Check if a week theme indicates recovery/taper."""
    theme_lower = theme.lower()
    return any(t in theme_lower for t in _RECOVERY_THEMES)


def _get_gpx_points(gpx_id: int, user_id: int):
    """Helper to get GPX file points, returns (points, bounds, error)."""
    gpx_repo = GPXFileRepository()
    gpx_file = gpx_repo.get_user_file(gpx_id, user_id)
    if not gpx_file or not gpx_file.data:
        return None, None, {'error': f'GPX route {gpx_id} not found'}
    points = gpx_file.data.get('points', [])
    bounds = gpx_file.data.get('bounds')
    if not points:
        return None, None, {'error': 'GPX route has no points'}
    return points, bounds, None


def _resolve_lat_lon(points, distance_km):
    """Find the closest point on a GPX track to a given distance in km.

    Returns (lat, lon) tuple or None if points are empty.
    """
    if not points:
        return None
    target_m = distance_km * 1000
    closest = None
    min_diff = float('inf')
    for p in points:
        diff = abs(p.get('distance', 0) - target_m)
        if diff < min_diff:
            min_diff = diff
            closest = p
    if closest:
        return closest.get('lat'), closest.get('lon')
    return None


def _compute_gpx_distance_km(points: list) -> float | None:
    """Compute total distance in km from GPX points list."""
    if not points:
        return None
    last_dist = points[-1].get('distance', 0)
    return last_dist / 1000 if last_dist else None


def _compute_gpx_elevation_gain(points: list) -> float:
    """Compute total elevation gain from GPX points list."""
    gain, _ = _compute_gpx_elevation(points)
    return gain


def _compute_gpx_elevation(points: list) -> tuple[float, float]:
    """Compute total elevation gain AND loss from GPX points list.

    Returns (gain, loss) where both are positive numbers.
    """
    gain = 0.0
    loss = 0.0
    prev_ele = None
    for p in points:
        ele = p.get('ele') or p.get('elevation')
        if ele is None:
            continue
        if prev_ele is not None:
            diff = ele - prev_ele
            if diff > 0:
                gain += diff
            else:
                loss += abs(diff)
        prev_ele = ele
    return gain, loss


def _classify_race_profile(gain: float, loss: float, distance_km: float) -> dict:
    """Classify race as loop, point-to-point uphill, or point-to-point downhill.

    Returns dict with:
      - type: 'loop', 'uphill_only', 'downhill_finish'
      - race_ratio: D+/km of the race itself
      - training_ratio: recommended D+/km for training loops (accounts for descent)
      - description: human-readable classification
    """
    if gain <= 0 or distance_km <= 0:
        return {'type': 'flat', 'race_ratio': 0, 'training_ratio': 0, 'description': 'flat race'}

    race_ratio = gain / distance_km
    balance = loss / gain if gain > 0 else 1.0  # 1.0 = perfect loop, 0.0 = pure uphill

    if balance < 0.3:
        # Mostly uphill (VK, uphill-only races)
        # Training loops will have descent — double the distance for same D+
        # e.g. VK 5km/1000m D+ → training: 10km loop (5km up + 5km down) with 1000m D+
        training_ratio = gain / (distance_km * 2)
        return {
            'type': 'uphill_only',
            'race_ratio': race_ratio,
            'training_ratio': training_ratio,
            'balance': balance,
            'description': (
                f'Uphill-dominant race ({balance:.0%} descent vs ascent). '
                f'Race ratio is {race_ratio:.0f}m/km but training loops need '
                f'descent too — target ~{training_ratio:.0f}m/km on loops, '
                f'or use treadmill/hill repeats for pure uphill work.'
            ),
        }
    elif balance > 1.3:
        # Mostly downhill (net-downhill point-to-point)
        training_ratio = race_ratio
        return {
            'type': 'downhill_finish',
            'race_ratio': race_ratio,
            'training_ratio': training_ratio,
            'balance': balance,
            'description': (
                f'Downhill-dominant race ({balance:.0%} descent vs ascent). '
                f'Focus on eccentric strength and downhill technique training.'
            ),
        }
    else:
        # Balanced loop (D+ ≈ D-)
        return {
            'type': 'loop',
            'race_ratio': race_ratio,
            'training_ratio': race_ratio,
            'balance': balance,
            'description': (
                f'Balanced loop race (D+/D- ratio: {balance:.0%}). '
                f'Training loops at {race_ratio:.0f}m/km match race demands.'
            ),
        }


def _inject_calendar_dates(weeks, race_date):
    """Add actual calendar dates to each day in the plan."""
    total_weeks = len(weeks)
    race_week_monday = race_date - timedelta(days=race_date.weekday())
    week1_monday = race_week_monday - timedelta(weeks=total_weeks - 1)
    for week in weeks:
        wn = week['week_number']
        week_monday = week1_monday + timedelta(weeks=wn - 1)
        week['start_date'] = week_monday.strftime('%Y-%m-%d')
        for day in week.get('days', []):
            offset = _DAY_OFFSETS.get(day['day'], 0)
            day['date'] = (week_monday + timedelta(days=offset)).strftime('%Y-%m-%d')


# ============================================================================
# Week Quality Assessment
# ============================================================================

def _assess_week_quality(days: list, week_number: int, theme: str) -> list:
    """Assess training quality of a validated week. Returns list of warning strings.

    Quality checks are soft warnings — they do NOT block validation.
    Recovery/taper weeks have relaxed requirements.
    """
    warnings = []
    workout_types = {d.get('workout_type') for d in days}

    if _is_recovery_week(theme):
        # Recovery weeks should not have high-intensity work
        high_intensity = workout_types & _HIGH_INTENSITY_TYPES
        if high_intensity:
            types_str = ', '.join(sorted(high_intensity))
            warnings.append(
                f"Week {week_number} is marked as '{theme}' but contains "
                f"high-intensity workouts ({types_str}). Recovery weeks "
                f"should focus on easy effort and rest."
            )
        return warnings

    # Non-recovery week checks
    if 'long_run' not in workout_types:
        warnings.append(
            f"Week {week_number}: No long run scheduled. A weekly long run "
            f"is the cornerstone workout for trail running endurance."
        )

    if not workout_types & _SPEED_WORKOUT_TYPES:
        warnings.append(
            f"Week {week_number}: No speed/intensity session (intervals, "
            f"tempo, or hill repeats). At least one is needed for "
            f"training stimulus and race fitness."
        )

    # Per-workout elevation density check.
    # Distance = total loop (including descent). D+/km gauges difficulty.
    for day in days:
        dist = day.get('distance_km', 0)
        elev = day.get('elevation_m', 0)
        if dist <= 0 or elev <= 0:
            continue
        elev_per_km = elev / dist
        day_name = day.get('day', '?')
        wtype = day.get('workout_type', '')

        if elev_per_km > 100:
            # VK-level: almost certainly an error
            warnings.append(
                f"Week {week_number}, {day_name}: {dist:.0f}km with {elev:.0f}m D+ "
                f"({elev_per_km:.0f}m/km) exceeds Vertical Kilometer steepness. "
                f"Distance must include descent — check that total km covers the "
                f"full loop, not just the uphill portion."
            )
        elif elev_per_km > 80:
            # Extreme mountain — possible but brutally hard
            warnings.append(
                f"Week {week_number}, {day_name}: {dist:.0f}km with {elev:.0f}m D+ "
                f"({elev_per_km:.0f}m/km) is extreme mountain terrain. This is a "
                f"peak-effort workout — ensure the athlete has mountain access, "
                f"adequate fitness, and recovery days around it."
            )
        elif elev_per_km > 60 and wtype in ('long_run', 'back_to_back'):
            # Long runs above 60m/km are race-simulation level effort
            warnings.append(
                f"Week {week_number}, {day_name}: long run at {elev_per_km:.0f}m/km "
                f"({dist:.0f}km with {elev:.0f}m D+) is race-simulation intensity. "
                f"Treat this as a key workout with recovery days before and after."
            )

    return warnings


def _assess_edit_impact(before_days: dict, after_days: dict,
                        week_number: int, theme: str) -> dict:
    """Assess the training impact of editing a week's workouts.

    Returns dict with severity, warnings, and suggestions so the LLM can
    inform the user about significant changes.
    """
    removed_key = []
    for day_name, after in after_days.items():
        before = before_days.get(day_name, {})
        old_type = before.get('workout_type')
        new_type = after.get('workout_type')
        if old_type == new_type:
            continue
        if old_type in _KEY_WORKOUT_TYPES and new_type not in _KEY_WORKOUT_TYPES:
            removed_key.append({
                'day': day_name,
                'was': old_type,
                'now': new_type,
            })

    warnings = []
    suggestions = []

    for removal in removed_key:
        was = removal['was'].replace('_', ' ')
        day = removal['day']
        if removal['was'] == 'long_run':
            warnings.append(
                f"Long run removed from {day}. This is the most important "
                f"weekly workout for endurance development."
            )
            suggestions.append(
                f"Consider moving the long run to another day this week "
                f"instead of removing it entirely."
            )
        elif removal['was'] in _SPEED_WORKOUT_TYPES:
            warnings.append(
                f"{was.title()} session removed from {day}. Speed/intensity "
                f"work is essential for race fitness."
            )
            suggestions.append(
                f"Try to keep at least one speed session per week. "
                f"Move it to another day if {day} doesn't work."
            )
        else:
            warnings.append(
                f"{was.title()} removed from {day}."
            )

    # Check post-edit week quality
    post_edit_days = [after_days[d] for d in after_days]
    quality_warnings = _assess_week_quality(post_edit_days, week_number, theme)
    warnings.extend(quality_warnings)

    # Determine severity
    removed_types = {r['was'] for r in removed_key}
    if removed_types & _HIGH_IMPACT_TYPES:
        severity = 'high'
    elif removed_key:
        severity = 'medium'
    else:
        severity = 'low'

    return {
        'severity': severity,
        'removed_key_workouts': removed_key if removed_key else None,
        'warnings': warnings,
        'suggestions': suggestions,
    }


def _validate_single_week(week_input: Dict,
                          race_distance_km: float = 0,
                          race_elevation_m: float = 0) -> Dict:
    """Validate and structure a single training week. Returns result dict.

    Args:
        week_input: Week data from the LLM
        race_distance_km: Target race distance (for auto-filling race day)
        race_elevation_m: Target race elevation gain (for auto-filling race day)
    """
    week_number = week_input.get('week_number', 1)
    theme = week_input.get('theme', 'General')
    total_km = week_input.get('total_km', 0)
    total_elevation_m = week_input.get('total_elevation_m', 0)
    days = week_input.get('days', [])

    if not days:
        return {
            'error': f'Week {week_number}: "days" array is required with at least one day.',
            'hint': (
                'Use single-week mode: call generate_training_week once per week '
                'with week_number, theme, total_km, total_elevation_m, and a days array. '
                'Each day needs: day (Monday-Sunday), workout_type, title, distance_km, elevation_m.'
            ),
            'week_number': week_number,
        }

    total_km = min(total_km, MAX_WEEKLY_KM)
    total_elevation_m = min(total_elevation_m, 10000)

    validated_days = []
    messages = []

    for day in days:
        day_name = day.get('day', '')
        if day_name not in VALID_DAYS:
            messages.append(f"Invalid day '{day_name}', skipping")
            continue

        workout_type = day.get('workout_type', 'easy')
        if workout_type not in VALID_WORKOUT_TYPES:
            messages.append(f"Invalid workout type '{workout_type}' for {day_name}, defaulting to 'easy'")
            workout_type = 'easy'

        distance_km = day.get('distance_km', 0)
        elevation_m = day.get('elevation_m', 0)

        # Auto-correct race_simulation workouts that are the actual race day
        # (LLM often puts placeholder values instead of real race distance/elevation)
        if workout_type == 'race_simulation' and race_distance_km > 0:
            if distance_km < race_distance_km * 0.5:
                messages.append(
                    f"{day_name}: race day distance corrected from {distance_km}km "
                    f"to {race_distance_km}km (actual race distance)"
                )
                distance_km = race_distance_km
            if race_elevation_m > 0 and elevation_m < race_elevation_m * 0.5:
                messages.append(
                    f"{day_name}: race day elevation corrected from {elevation_m}m "
                    f"to {race_elevation_m}m (actual race elevation)"
                )
                elevation_m = race_elevation_m

        if distance_km > MAX_SINGLE_RUN_KM:
            messages.append(f"{day_name}: clamped distance from {distance_km}km to {MAX_SINGLE_RUN_KM}km")
            distance_km = MAX_SINGLE_RUN_KM

        # Auto-correct unrealistic elevation density (not race_simulation which was handled above)
        if workout_type != 'race_simulation' and distance_km > 0 and elevation_m > 0:
            elev_per_km = elevation_m / distance_km
            # Max elevation density based on workout type
            if workout_type in ('hill_repeats', 'vert_session'):
                max_ratio = 80  # steep but must include descent distance
            elif workout_type in ('long_run', 'back_to_back'):
                max_ratio = 70  # race-ratio + margin
            else:
                max_ratio = 80  # general cap

            # Use race ratio as reference if available — don't exceed 1.5x race ratio
            if race_distance_km > 0 and race_elevation_m > 0:
                race_ratio = race_elevation_m / race_distance_km
                max_ratio = min(max_ratio, race_ratio * 1.5)
                max_ratio = max(max_ratio, 50)  # floor at 50 to avoid clamping everything on flat races

            if elev_per_km > max_ratio:
                corrected_elev = round(distance_km * max_ratio)
                messages.append(
                    f"{day_name}: elevation corrected from {elevation_m:.0f}m to {corrected_elev}m "
                    f"({elev_per_km:.0f}m/km → {max_ratio:.0f}m/km — "
                    f"distance must include descent)"
                )
                elevation_m = corrected_elev

        intensity = day.get('intensity', 'easy')
        if intensity not in VALID_INTENSITIES:
            intensity = 'easy'

        day_data = {
            'day': day_name,
            'workout_type': workout_type,
            'title': day.get('title', f'{workout_type.replace("_", " ").title()}'),
            'distance_km': round(distance_km, 1),
            'duration_min': day.get('duration_min', 0),
            'elevation_m': elevation_m,
            'intensity': intensity,
            'notes': day.get('notes', ''),
        }

        steps = day.get('steps')
        if steps:
            from services.workout_service import validate_steps, compute_step_summaries
            valid, err = validate_steps(steps)
            if valid:
                day_data['steps'] = steps
                summaries = compute_step_summaries(steps)
                if summaries['distance_km'] is not None:
                    day_data['distance_km'] = summaries['distance_km']
                if summaries['duration_min'] is not None:
                    day_data['duration_min'] = summaries['duration_min']
                if summaries['elevation_m'] is not None:
                    day_data['elevation_m'] = summaries['elevation_m']
            else:
                messages.append(f"{day_name}: invalid steps ({err}), using flat workout")

        validated_days.append(day_data)

    actual_km = sum(d['distance_km'] for d in validated_days)
    actual_elev = sum(d.get('elevation_m', 0) or 0 for d in validated_days)

    quality_warnings = _assess_week_quality(validated_days, week_number, theme)

    return {
        'week_number': week_number,
        'theme': theme,
        'total_km': round(actual_km, 1),
        'total_elevation_m': round(actual_elev),
        'days': validated_days,
        'messages': messages if messages else None,
        'quality_warnings': quality_warnings if quality_warnings else None,
        'valid': True,
    }


# ============================================================================
# Timeline Reasonableness
# ============================================================================

def _get_minimum_weeks_for_distance(distance_km: float) -> int | None:
    """Interpolate minimum weeks for a given race distance."""
    if distance_km < 21:
        return None  # Too short to warrant a timeline check
    for dist, weeks in _RACE_MINIMUM_WEEKS:
        if distance_km <= dist:
            return weeks
    # Beyond 160km, extrapolate linearly from 100K-100mi slope
    extra_km = distance_km - 160
    extra_weeks = int(extra_km / 20)  # ~1 week per 20km beyond 100mi
    return 22 + extra_weeks


def _get_peak_volume_for_distance(distance_km: float) -> float | None:
    """Get the midpoint of recommended peak weekly volume for a distance."""
    if distance_km < 21:
        return None
    for dist, (low, high) in _RACE_PEAK_VOLUME:
        if distance_km <= dist:
            return (low + high) / 2
    # Beyond 160km, use 100mi values
    return (115 + 160) / 2


def _assess_timeline_reasonableness(
    total_weeks: int,
    target_distance_km: float | None,
    target_gpx_id: int | None,
    user_id: int,
) -> list[str]:
    """Returns list of advisory strings about timeline and suggested plan approach.

    Analyzes the user's training history to determine whether they already
    have a solid base, and if so, suggests a compressed plan that covers
    only the later phases (build -> peak -> taper). If not, warns and
    recommends starting earlier next time.
    """
    from models import Activity

    warnings: list[str] = []

    # --- Resolve target distance ---
    distance_km = target_distance_km
    if target_gpx_id and not distance_km:
        try:
            gpx_repo = GPXFileRepository()
            gpx_file = gpx_repo.get_user_file(target_gpx_id, user_id)
            if gpx_file and gpx_file.data:
                points = gpx_file.data.get('points', [])
                computed = _compute_gpx_distance_km(points)
                if computed and computed > 0:
                    distance_km = computed
        except Exception as e:
            logger.debug(f"Could not compute GPX distance for timeline check: {e}")

    if not distance_km or distance_km < 21:
        return warnings

    if total_weeks <= 0:
        return warnings

    # --- Get book minimums ---
    book_min_weeks = _get_minimum_weeks_for_distance(distance_km)
    if book_min_weeks is None:
        return warnings

    peak_volume = _get_peak_volume_for_distance(distance_km)
    distance_label = f"{distance_km:.0f}km"

    # If plan is already at or above the book minimum, no advisory needed
    if total_weeks >= book_min_weeks:
        return warnings

    # --- Query user's Strava history to assess existing fitness ---
    has_strava_data = False
    avg_weekly_km = 0.0
    longest_run_km = 0.0
    consistency_ratio = 0.0
    avg_weekly_elevation_m = 0.0

    try:
        cutoff_12w = datetime.now(timezone.utc) - timedelta(weeks=12)
        cutoff_8w = datetime.now(timezone.utc) - timedelta(weeks=8)

        activities_12w = (
            Activity.query
            .filter(Activity.user_id == user_id)
            .filter(Activity.start_date >= cutoff_12w)
            .order_by(Activity.start_date.asc())
            .all()
        )

        if activities_12w:
            has_strava_data = True

            distances = [a.distance / 1000 for a in activities_12w]
            longest_run_km = max(distances) if distances else 0.0

            from collections import defaultdict
            weekly_km: dict[str, float] = defaultdict(float)
            weekly_runs: dict[str, int] = defaultdict(int)
            weekly_elev: dict[str, float] = defaultdict(float)

            for act in activities_12w:
                if act.start_date >= cutoff_8w:
                    iso_year, iso_week, _ = act.start_date.isocalendar()
                    key = f"{iso_year}-W{iso_week:02d}"
                    weekly_km[key] += act.distance / 1000
                    weekly_runs[key] += 1
                    weekly_elev[key] += getattr(act, 'total_elevation_gain', 0) or 0

            if weekly_km:
                avg_weekly_km = sum(weekly_km.values()) / max(len(weekly_km), 1)
                avg_weekly_elevation_m = sum(weekly_elev.values()) / max(len(weekly_elev), 1)

            consistent_weeks = sum(1 for runs in weekly_runs.values() if runs >= 3)
            total_counted_weeks = max(len(weekly_runs), 1)
            consistency_ratio = consistent_weeks / min(total_counted_weeks, 8)

    except Exception as e:
        logger.debug(f"Could not query Strava history for timeline check: {e}")

    # --- Assess fitness level and decide approach ---
    has_solid_base = False
    fitness_notes = []

    if has_strava_data:
        volume_ok = peak_volume and avg_weekly_km >= 0.5 * peak_volume
        long_run_ok = longest_run_km >= 0.4 * distance_km
        consistent = consistency_ratio >= 0.5

        if volume_ok:
            fitness_notes.append(f"avg weekly volume {avg_weekly_km:.0f}km (>=50% of peak target)")
        if long_run_ok:
            fitness_notes.append(f"longest recent run {longest_run_km:.0f}km (>=40% of race distance)")
        if consistent:
            fitness_notes.append(f"training consistency {consistency_ratio:.0%}")

        # User has a solid base if at least 2 of 3 criteria met
        has_solid_base = sum([bool(volume_ok), bool(long_run_ok), bool(consistent)]) >= 2
    else:
        warnings.append(
            f"No Strava training history available. For a {distance_label} race, "
            f"a full preparation plan is typically {book_min_weeks} weeks. "
            f"Connect Strava for a personalized assessment of whether a "
            f"compressed {total_weeks}-week plan is appropriate for your fitness level."
        )
        return warnings

    # --- Generate constructive advice based on fitness ---
    if has_solid_base:
        # User is fit — propose a compressed plan covering later phases
        # Calculate which phases to include
        if total_weeks >= 3:
            # Enough for build + peak + taper
            taper_weeks = min(2, max(1, total_weeks // 5))
            peak_weeks = min(2, max(1, (total_weeks - taper_weeks) // 3))
            build_weeks = total_weeks - taper_weeks - peak_weeks
            phase_suggestion = (
                f"With {total_weeks} weeks and your current fitness "
                f"({'; '.join(fitness_notes)}), a compressed plan is viable. "
                f"Suggested structure: {build_weeks}w Build -> {peak_weeks}w Peak -> "
                f"{taper_weeks}w Taper. This skips the base phase because your "
                f"recent training already provides that foundation. "
                f"For optimal preparation next time, start planning {book_min_weeks} "
                f"weeks out to include a proper base-building phase."
            )
        else:
            # Very short — peak + taper only
            phase_suggestion = (
                f"With only {total_weeks} weeks, this plan can only cover "
                f"sharpening and taper. Your recent training ({'; '.join(fitness_notes)}) "
                f"suggests you have a base to work from, so focus on race-specific "
                f"workouts and a short taper. For optimal preparation next time, "
                f"start planning {book_min_weeks} weeks out."
            )
        warnings.append(f"[COMPRESSED PLAN] {phase_suggestion}")
    else:
        # User is NOT fit enough for compressed plan — be honest but constructive
        gaps = []
        if not (peak_volume and avg_weekly_km >= 0.5 * peak_volume):
            target_vol = peak_volume * 0.5 if peak_volume else 0
            gaps.append(f"weekly volume ({avg_weekly_km:.0f}km, target >={target_vol:.0f}km)")
        if not (longest_run_km >= 0.4 * distance_km):
            target_long = distance_km * 0.4
            gaps.append(f"longest run ({longest_run_km:.0f}km, target >={target_long:.0f}km)")
        if consistency_ratio < 0.5:
            gaps.append(f"training consistency ({consistency_ratio:.0%}, target >=50%)")

        warnings.append(
            f"[TIMELINE ADVISORY] A {distance_label} race typically needs "
            f"{book_min_weeks} weeks of preparation. Your current fitness shows gaps "
            f"in: {'; '.join(gaps)}. A {total_weeks}-week plan will be tight — "
            f"focus entirely on building volume and consistency rather than speed work. "
            f"Consider targeting a shorter distance first, or extending to "
            f"{book_min_weeks} weeks if the race date allows. "
            f"If you proceed with {total_weeks} weeks, the plan should be "
            f"conservative: mostly easy Z1-Z2 runs with a gradual volume increase "
            f"and a 1-week taper."
        )

    return warnings


# ============================================================================
# Coaching Knowledge Warnings (cross-week validation)
# ============================================================================

def _assess_coaching_knowledge_warnings(
    valid_weeks: list, user_id: int, target_gpx_id: int | None = None
) -> list:
    """Apply cross-week coaching rules to validated weeks.

    Includes 10% progression check, ADS gating, recovery-week volume,
    elevation specificity vs race ratio, and back-to-back validation.
    Returns list of warning strings.
    """
    warnings = []
    if not valid_weeks:
        return warnings

    # Sort weeks by week_number for sequential analysis
    sorted_weeks = sorted(valid_weeks, key=lambda w: w.get('week_number', 0))

    # --- Rule 1: 10% Volume Progression Rule ---
    for i in range(1, len(sorted_weeks)):
        prev_week = sorted_weeks[i - 1]
        curr_week = sorted_weeks[i]
        prev_km = prev_week.get('total_km', 0)
        curr_km = curr_week.get('total_km', 0)
        curr_wn = curr_week.get('week_number', i + 1)

        if prev_km <= 0 or curr_km <= 0:
            continue

        # Skip check if previous week was recovery (bigger jumps are OK coming back)
        prev_theme = prev_week.get('theme', '')
        if _is_recovery_week(prev_theme):
            continue

        increase_pct = ((curr_km - prev_km) / prev_km) * 100
        if increase_pct > 10:
            warnings.append(
                f"Week {curr_wn}: volume jumps {increase_pct:.0f}% over the previous week "
                f"({prev_km:.0f}km -> {curr_km:.0f}km). Keep weekly increases at ~10% "
                f"or less to reduce injury risk."
            )

    # --- Rule 2: AeT/LT-based Intensity Gating (ADS detection) ---
    try:
        params_repo = UserLearnedParamsRepository()
        learned_params = params_repo.get_by_user(user_id)
        if learned_params and learned_params.n_activities_used < 10:
            # Few calibration activities suggests the athlete is new to structured
            # training — suspect Aerobic Deficiency Syndrome and flag Z3+ work.
            for week in sorted_weeks:
                wn = week.get('week_number', 0)
                theme = week.get('theme', '')
                if _is_recovery_week(theme):
                    continue
                days = week.get('days', [])
                z3_types = {
                    d.get('workout_type') for d in days
                } & _Z3_PLUS_WORKOUT_TYPES
                if z3_types:
                    types_str = ', '.join(sorted(z3_types))
                    warnings.append(
                        f"Week {wn}: includes Z3+ workouts ({types_str}) but calibration "
                        f"is based on only {learned_params.n_activities_used} activities. "
                        f"Athletes new to structured training may have Aerobic Deficiency "
                        f"Syndrome (ADS). Consider focusing on Z1-Z2 base building first "
                        f"and introducing intensity gradually after building aerobic capacity."
                    )
    except Exception as e:
        logger.debug(f"Could not check ADS status for user {user_id}: {e}")

    # --- Rule 3: Recovery Week Volume Validation ---
    # Find peak build week volume to compare against recovery weeks
    build_week_kms = [
        w.get('total_km', 0) for w in sorted_weeks
        if not _is_recovery_week(w.get('theme', ''))
    ]
    peak_build_km = max(build_week_kms) if build_week_kms else 0

    if peak_build_km > 0:
        for week in sorted_weeks:
            theme = week.get('theme', '')
            if not _is_recovery_week(theme):
                continue
            wn = week.get('week_number', 0)
            recovery_km = week.get('total_km', 0)
            ratio = recovery_km / peak_build_km
            if ratio > 0.70:
                warnings.append(
                    f"Week {wn} ('{theme}'): recovery week volume ({recovery_km:.0f}km) "
                    f"is {ratio:.0%} of peak build week ({peak_build_km:.0f}km). "
                    f"Recovery weeks should be 40-60% of peak volume. Reduce volume to "
                    f"allow proper adaptation and recovery."
                )

    # --- Rule 4: Elevation Specificity (race ratio based) ---
    race_ratio = 0.0  # D+/km of the target race
    if target_gpx_id:
        try:
            gpx_repo = GPXFileRepository()
            gpx_file = gpx_repo.get_user_file(target_gpx_id, user_id)
            if gpx_file and gpx_file.data:
                points = gpx_file.data.get('points', [])
                race_dist = gpx_file.data.get('total_distance_km') or 0
                if points:
                    race_elevation_gain = _compute_gpx_elevation_gain(points)
                    if race_elevation_gain > 0 and race_dist > 0:
                        race_ratio = race_elevation_gain / race_dist

                        # 4a: Peak weekly elevation should hit 100% of race elevation
                        peak_week_elev = max(
                            (w.get('total_elevation_m', 0) for w in sorted_weeks), default=0
                        )
                        if peak_week_elev < race_elevation_gain:
                            pct = (peak_week_elev / race_elevation_gain * 100)
                            warnings.append(
                                f"Elevation specificity: peak training week elevation "
                                f"({peak_week_elev:.0f}m D+) is only {pct:.0f}% of race elevation "
                                f"({race_elevation_gain:.0f}m D+). Peak weeks should hit 100% of "
                                f"race D+ in at least 2 late build weeks. Consider peak weeks "
                                f"around {race_elevation_gain * 1.2:.0f}m D+."
                            )

                        # 4b: Check per-workout D+/km matches race ratio
                        for week in sorted_weeks:
                            wn = week.get('week_number', 0)
                            if _is_recovery_week(week.get('theme', '')):
                                continue
                            for day in week.get('days', []):
                                dist = day.get('distance_km', 0)
                                elev = day.get('elevation_m', 0)
                                wtype = day.get('workout_type', '')
                                if dist <= 0 or elev <= 0:
                                    continue
                                if wtype in ('rest', 'recovery'):
                                    continue
                                day_ratio = elev / dist
                                day_name = day.get('day', '?')

                                # Flag if workout ratio is way off race ratio
                                if day_ratio < race_ratio * 0.3 and wtype in ('long_run', 'back_to_back'):
                                    warnings.append(
                                        f"Week {wn}, {day_name}: long run at {day_ratio:.0f}m/km "
                                        f"is much flatter than race ratio ({race_ratio:.0f}m/km). "
                                        f"Long runs should train at race-like elevation density."
                                    )
        except Exception as e:
            logger.debug(f"Could not check elevation specificity: {e}")

    # --- Rule 5: Back-to-back Workout Validation ---
    for week in sorted_weeks:
        wn = week.get('week_number', 0)
        days = week.get('days', [])
        # Build a day-name to workout_type map
        day_types = {d.get('day'): d.get('workout_type') for d in days}

        for day_data in days:
            if day_data.get('workout_type') != 'back_to_back':
                continue
            day_name = day_data.get('day', '')
            try:
                day_idx = _DAY_ORDER.index(day_name)
            except ValueError:
                continue
            if day_idx == 0:
                # Monday — no preceding day in this week
                warnings.append(
                    f"Week {wn}: back_to_back workout on {day_name} has no preceding "
                    f"day in the week. The back-to-back pattern requires a long_run "
                    f"on the day before (e.g., Saturday long_run + Sunday back_to_back)."
                )
                continue
            prev_day_name = _DAY_ORDER[day_idx - 1]
            prev_type = day_types.get(prev_day_name)
            if prev_type != 'long_run':
                prev_label = prev_type.replace('_', ' ') if prev_type else 'no workout'
                warnings.append(
                    f"Week {wn}: back_to_back workout on {day_name} should follow a "
                    f"long_run, but {prev_day_name} has '{prev_label}'. The back-to-back "
                    f"pattern is: long_run + back_to_back on consecutive days to simulate "
                    f"race fatigue."
                )

    return warnings

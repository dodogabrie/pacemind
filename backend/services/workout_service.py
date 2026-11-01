"""Workout service for structured step validation and summary computation."""

import re
from typing import Any, Dict, List, Optional, Tuple


VALID_STEP_TYPES = {'warmup', 'work', 'rest', 'cooldown', 'repeat'}
VALID_TARGET_TYPES = {'effort', 'hr', 'pace', 'power', 'open'}
VALID_TERRAINS = {'trail', 'road', 'mixed'}
VALID_ELEV_DIRECTIONS = {'up', 'down', 'round_trip'}
MAX_NESTING_DEPTH = 1  # Only repeat can nest, and only one level deep
MAX_REPEATS = 30
MAX_RPE = 10


def validate_steps(steps: List[Dict]) -> Tuple[bool, Optional[str]]:
    """Validate a list of workout steps.

    Returns:
        (is_valid, error_message)
    """
    if not isinstance(steps, list):
        return False, 'steps must be a list'

    if len(steps) == 0:
        return False, 'steps must not be empty'

    for i, step in enumerate(steps):
        valid, err = _validate_step(step, depth=0, index=i)
        if not valid:
            return False, err

    return True, None


def _validate_step(step: Dict, depth: int, index: int) -> Tuple[bool, Optional[str]]:
    """Validate a single step, recursively for repeats."""
    if not isinstance(step, dict):
        return False, f'Step {index}: must be an object'

    step_type = step.get('type')
    if step_type not in VALID_STEP_TYPES:
        return False, f'Step {index}: invalid type "{step_type}"'

    if step_type == 'repeat':
        if depth >= MAX_NESTING_DEPTH:
            return False, f'Step {index}: repeats cannot be nested'

        repeats = step.get('repeats', 0)
        if not isinstance(repeats, int) or repeats < 1 or repeats > MAX_REPEATS:
            return False, f'Step {index}: repeats must be 1-{MAX_REPEATS}'

        child_steps = step.get('steps', [])
        if not child_steps:
            return False, f'Step {index}: repeat must have child steps'

        for j, child in enumerate(child_steps):
            valid, err = _validate_step(child, depth + 1, f'{index}.{j}')
            if not valid:
                return False, err
    else:
        # Non-repeat steps need at least one measure
        has_measure = any(
            step.get(f) and step.get(f) > 0
            for f in ('duration_min', 'distance_m', 'elevation_gain_m')
        )
        if not has_measure:
            return False, f'Step {index}: needs duration_min, distance_m, or elevation_gain_m'

    # Validate target if present
    target = step.get('target')
    if target:
        valid, err = _validate_target(target, index)
        if not valid:
            return False, err

    # Validate terrain if present
    terrain = step.get('terrain')
    if terrain and terrain not in VALID_TERRAINS:
        return False, f'Step {index}: invalid terrain "{terrain}"'

    # Validate segment_ref if present (route-linked steps)
    segment_ref = step.get('segment_ref')
    if segment_ref:
        if not isinstance(segment_ref, dict):
            return False, f'Step {index}: segment_ref must be an object'
        if 'start_idx' not in segment_ref or 'end_idx' not in segment_ref:
            return False, f'Step {index}: segment_ref needs start_idx and end_idx'

    return True, None


def _validate_target(target: Dict, step_index) -> Tuple[bool, Optional[str]]:
    """Validate a step target."""
    if not isinstance(target, dict):
        return False, f'Step {step_index}: target must be an object'

    target_type = target.get('type')
    if target_type not in VALID_TARGET_TYPES:
        return False, f'Step {step_index}: invalid target type "{target_type}"'

    if target_type == 'effort':
        rpe = target.get('rpe')
        if rpe is not None and (not isinstance(rpe, (int, float)) or rpe < 1 or rpe > MAX_RPE):
            return False, f'Step {step_index}: RPE must be 1-{MAX_RPE}'

    if target_type == 'hr':
        zone = target.get('zone')
        if zone is not None and (not isinstance(zone, int) or zone < 1 or zone > 5):
            return False, f'Step {step_index}: HR zone must be 1-5'

    if target_type == 'power':
        zone = target.get('zone')
        if zone is not None and (not isinstance(zone, int) or zone < 1 or zone > 5):
            return False, f'Step {step_index}: power zone must be 1-5'

    return True, None


def compute_step_summaries(steps: List[Dict]) -> Dict:
    """Compute total distance, duration estimate, and elevation from steps.

    Returns:
        Dict with distance_km, duration_min, elevation_m, step_count
    """
    totals = {'distance_m': 0, 'duration_min': 0, 'elevation_gain_m': 0, 'step_count': 0}
    _accumulate_steps(steps, totals, multiplier=1)

    return {
        'distance_km': round(totals['distance_m'] / 1000, 1) if totals['distance_m'] else None,
        'duration_min': round(totals['duration_min'], 0) if totals['duration_min'] else None,
        'elevation_m': round(totals['elevation_gain_m'], 0) if totals['elevation_gain_m'] else None,
        'step_count': totals['step_count'],
    }


def _accumulate_steps(steps: List[Dict], totals: Dict, multiplier: int):
    """Recursively accumulate step measures into totals."""
    for step in steps:
        if step.get('type') == 'repeat':
            reps = step.get('repeats', 1)
            _accumulate_steps(step.get('steps', []), totals, multiplier * reps)
        else:
            totals['step_count'] += multiplier
            totals['distance_m'] += (step.get('distance_m', 0) or 0) * multiplier
            totals['duration_min'] += (step.get('duration_min', 0) or 0) * multiplier
            totals['elevation_gain_m'] += (step.get('elevation_gain_m', 0) or 0) * multiplier


def steps_to_text(steps: List[Dict], hr_zones: Optional[Dict] = None,
                  power_zones: Optional[Dict] = None) -> str:
    """Render structured steps as human-readable text for ICS/display.

    Args:
        hr_zones: optional zone_name -> {min_bpm, max_bpm} map (from
            pace_zone_service.compute_hr_zones). When supplied, HR-targeted steps
            render the resolved bpm range, e.g. "Z2 (132-145 bpm)".
        power_zones: optional zone_name -> {min_w, max_w} map (from
            pace_zone_service.compute_power_zones). When supplied, power-targeted
            steps render the resolved watt range, e.g. "Z3 (210-234 W)".
    """
    lines = []
    _render_steps(steps, lines, indent=0, hr_zones=hr_zones, power_zones=power_zones)
    return '\n'.join(lines)


def build_steps_from_route(route_id: int, workout_type: str, focus: str = 'climbing') -> List[Dict]:
    """Build workout steps from a training route's segments.

    Args:
        route_id: TrainingRoute ID
        workout_type: e.g. 'hill_repeats', 'long_run', 'race_simulation'
        focus: 'climbing', 'descending', 'endurance'

    Returns:
        List of structured step dicts with segment_ref
    """
    from repositories import TrainingRouteRepository
    repo = TrainingRouteRepository()
    route = repo.get_by_id(route_id)
    if not route or not route.route_data:
        return []

    points = route.route_data
    if len(points) < 2:
        return []

    steps = [{'type': 'warmup', 'duration_min': 10, 'target': {'type': 'effort', 'rpe': 3}}]

    # Analyze route segments to build work steps
    import numpy as np
    elevations = [p.get('elevation', 0) for p in points]
    distances = [p.get('distance', 0) for p in points]

    # Split into ~500m chunks for step building
    chunk_size = 500  # meters
    total_dist = distances[-1] if distances else 0
    n_chunks = max(1, int(total_dist / chunk_size))

    chunk_indices = []
    for c in range(n_chunks):
        start_dist = c * chunk_size
        end_dist = min((c + 1) * chunk_size, total_dist)
        # Find closest point indices
        start_idx = _find_closest_index(distances, start_dist)
        end_idx = _find_closest_index(distances, end_dist)
        if end_idx <= start_idx:
            end_idx = min(start_idx + 1, len(points) - 1)
        chunk_indices.append((start_idx, end_idx))

    for start_idx, end_idx in chunk_indices:
        elev_start = elevations[start_idx]
        elev_end = elevations[end_idx]
        elev_change = elev_end - elev_start
        dist_m = distances[end_idx] - distances[start_idx]

        if dist_m < 10:
            continue

        grade = (elev_change / dist_m * 100) if dist_m > 0 else 0

        # Determine step type and effort based on focus and grade
        if grade > 5 and focus in ('climbing', 'endurance'):
            step = {
                'type': 'work',
                'distance_m': round(dist_m),
                'elevation_gain_m': round(max(0, elev_change)),
                'target': {'type': 'effort', 'rpe': 7 if workout_type == 'hill_repeats' else 6},
                'terrain': 'trail',
                'segment_ref': {'start_idx': start_idx, 'end_idx': end_idx},
                'notes': f'Climb at {grade:.0f}% grade',
            }
        elif grade < -5 and focus in ('descending', 'endurance'):
            step = {
                'type': 'work',
                'distance_m': round(dist_m),
                'target': {'type': 'effort', 'rpe': 5},
                'terrain': 'trail',
                'segment_ref': {'start_idx': start_idx, 'end_idx': end_idx},
                'notes': f'Descent at {grade:.0f}% grade — controlled pace',
            }
        else:
            step = {
                'type': 'work',
                'distance_m': round(dist_m),
                'target': {'type': 'effort', 'rpe': 5 if workout_type == 'easy' else 6},
                'terrain': 'trail' if abs(grade) > 2 else 'road',
                'segment_ref': {'start_idx': start_idx, 'end_idx': end_idx},
            }

        steps.append(step)

    steps.append({'type': 'cooldown', 'duration_min': 10, 'target': {'type': 'effort', 'rpe': 3}})
    return steps


def _find_closest_index(distances: list, target_dist: float) -> int:
    """Find the index of the point closest to target_dist."""
    best_idx = 0
    best_diff = abs(distances[0] - target_dist)
    for i, d in enumerate(distances):
        diff = abs(d - target_dist)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


_TYPE_TO_KEYWORD = {
    'warmup': 'Warmup',
    'work': 'Run',
    'rest': 'Recovery',
    'cooldown': 'Cooldown',
}


def _format_distance(distance_m: float) -> str:
    if distance_m >= 1000:
        km = distance_m / 1000
        return f"{km:g}km"
    return f"{int(round(distance_m))}m"


def _format_duration(minutes: float) -> str:
    minutes = float(minutes)
    if minutes >= 60 and minutes == int(minutes):
        h = int(minutes // 60)
        m = int(minutes - h * 60)
        return f"{h}h{m}min" if m else f"{h}h"
    if minutes < 1:
        return f"{int(round(minutes * 60))}s"
    return f"{minutes:g}min"


def _elevation_sign(direction: Optional[str], inside_repeat: bool) -> str:
    """Map a step's elevation_direction (or positional default) to the text sign."""
    if direction == 'up':
        return '+'
    if direction == 'down':
        return '-'
    if direction == 'round_trip':
        return '+-'
    # No explicit direction: positional default
    return '+' if inside_repeat else '+-'


def _render_target(target: Dict, hr_zones: Optional[Dict] = None,
                   power_zones: Optional[Dict] = None) -> Optional[str]:
    if not target:
        return None
    t = target.get('type')
    if t == 'effort':
        return f"RPE {target.get('rpe', '?')}"
    if t == 'hr':
        zone = target.get('zone')
        if not zone:
            return None
        bpm = _hr_zone_bpm(zone, hr_zones)
        return f"Z{zone} ({bpm})" if bpm else f"Z{zone}"
    if t == 'power':
        zone = target.get('zone')
        if not zone:
            return None
        watts = _power_zone_watts(zone, power_zones)
        return f"Z{zone} ({watts})" if watts else f"Z{zone}"
    if t == 'pace':
        zone = target.get('zone')
        if not zone:
            return None
        # Pace can be a "M:SS/km" string or a zone label
        if isinstance(zone, str) and re.match(r'^\d+:\d{2}', zone):
            z = zone if '/km' in zone else f"{zone}/km"
            return f"@ {z}"
        return f"@ {zone}"
    return None


# Workout HR targets carry a 1-5 zone index; index 1 maps to the easiest zone.
_HR_ZONE_BY_INDEX = ['recovery', 'easy', 'tempo', 'threshold', 'interval']


def _hr_zone_bpm(zone: int, hr_zones: Optional[Dict]) -> Optional[str]:
    """Resolve a 1-5 HR zone index to a "min-max bpm" string, if zones known."""
    if not hr_zones or not isinstance(zone, int) or not (1 <= zone <= 5):
        return None
    band = hr_zones.get(_HR_ZONE_BY_INDEX[zone - 1])
    if not band or band.get('min_bpm') is None or band.get('max_bpm') is None:
        return None
    return f"{band['min_bpm']}-{band['max_bpm']} bpm"


# Power targets use the same 1-5 zone index convention as HR targets.
_POWER_ZONE_BY_INDEX = ['recovery', 'easy', 'tempo', 'threshold', 'interval']


def _power_zone_watts(zone: int, power_zones: Optional[Dict]) -> Optional[str]:
    """Resolve a 1-5 power zone index to a "min-max W" string, if zones known."""
    if not power_zones or not isinstance(zone, int) or not (1 <= zone <= 5):
        return None
    band = power_zones.get(_POWER_ZONE_BY_INDEX[zone - 1])
    if not band or band.get('min_w') is None or band.get('max_w') is None:
        return None
    return f"{band['min_w']}-{band['max_w']} W"


def _render_steps(steps: List[Dict], lines: List[str], indent: int,
                  hr_zones: Optional[Dict] = None,
                  power_zones: Optional[Dict] = None):
    """Render steps to PaceMind workout syntax (round-trippable)."""
    prefix = '  ' * indent
    inside_repeat = indent > 0
    for step in steps:
        step_type = step.get('type', 'work')

        if step_type == 'repeat':
            reps = step.get('repeats', 1)
            lines.append(f'{prefix}{reps}x:')
            _render_steps(step.get('steps', []), lines, indent + 1,
                          hr_zones=hr_zones, power_zones=power_zones)
            continue

        label = _TYPE_TO_KEYWORD.get(step_type, 'Run')
        parts: List[str] = [label]

        if step.get('distance_m'):
            parts.append(_format_distance(step['distance_m']))

        if step.get('elevation_gain_m'):
            sign = _elevation_sign(step.get('elevation_direction'), inside_repeat)
            parts.append(f"{sign}{int(round(step['elevation_gain_m']))}m")

        if step.get('duration_min'):
            parts.append(_format_duration(step['duration_min']))

        rendered_target = _render_target(step.get('target') or {},
                                         hr_zones=hr_zones, power_zones=power_zones)
        if rendered_target:
            parts.append(rendered_target)

        if step.get('terrain'):
            parts.append(f"on {step['terrain']}")

        line = ' '.join(parts)
        if step.get('notes'):
            line += f" # {step['notes']}"
        lines.append(f"{prefix}{line}")


# ---------------------------------------------------------------------------
# Text -> structured steps parser (PaceMind workout syntax v1)
# ---------------------------------------------------------------------------

# Step keyword -> internal type
# TODO(i18n-gap #92 — see GH issues): user-facing English built server-side.
# Italian UI shows it verbatim; return a key + params and render with $t on the client.
_KEYWORD_TO_TYPE = {
    'warmup': 'warmup', 'wu': 'warmup', 'riscaldamento': 'warmup',
    'cooldown': 'cooldown', 'cd': 'cooldown', 'defaticamento': 'cooldown',
    'recovery': 'rest', 'recupero': 'rest', 'rest': 'rest',
    'riposo': 'rest', 'jog': 'rest',
    'run': 'work', 'work': 'work', 'corsa': 'work', 'tempo': 'work',
}

_TERRAIN_ALIASES = {
    'road': 'road', 'strada': 'road',
    'trail': 'trail', 'sentiero': 'trail',
    'mixed': 'mixed', 'misto': 'mixed',
}

_REPEAT_RE = re.compile(r'^(\d+)\s*x\s*:\s*$', re.IGNORECASE)
_NOTES_HASH_RE = re.compile(r'#\s*(.*)$')
_NOTES_PAREN_RE = re.compile(r'\(([^)]+)\)')
_TERRAIN_RE = re.compile(r'\bon\s+([a-zA-Zàèéìòù]+)\b', re.IGNORECASE)
# Elevation: signed prefix form, e.g. "+200m", "-200m", "+-200m", "±200m"
_ELEV_PREFIX_RE = re.compile(r'(\+\-|\-\+|±|\+|\-)\s*(\d+(?:\.\d+)?)\s*m\b(?!in)', re.IGNORECASE)
# Elevation: suffix form, e.g. "200m D+", "150m D-", "200m D+-"
_ELEV_SUFFIX_RE = re.compile(r'(\d+(?:\.\d+)?)\s*m\s*D\s*(\+\-|\-\+|±|\+|\-)', re.IGNORECASE)
# Hours+minutes duration like 1h30 / 1h30min / 2h
_DURATION_HOURS_RE = re.compile(r'\b(\d+)h(\d+)?(?:min)?\b', re.IGNORECASE)
# Plain minutes
_DURATION_MIN_RE = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*min\b', re.IGNORECASE)
# Plain seconds (only with explicit s suffix, not 5s of "rest")
_DURATION_SEC_RE = re.compile(r'(?<![\d.a-zA-Z])(\d+)\s*s\b', re.IGNORECASE)
# Distance km/m (no leading sign — those are elevation)
_DISTANCE_KM_RE = re.compile(r'(?<![+\-\d.a-zA-Z])(\d+(?:\.\d+)?)\s*km\b', re.IGNORECASE)
# Distance in meters: number+m, NOT preceded by sign or letter, NOT followed by "in" (min) or "D"
_DISTANCE_M_RE = re.compile(r'(?<![+\-\d.a-zA-Z])(\d+(?:\.\d+)?)\s*m\b(?!in)(?!\s*D)', re.IGNORECASE)
# Targets
_HR_ZONE_RE = re.compile(r'(?<![@/])\bZ([1-5])\b', re.IGNORECASE)
_RPE_RE = re.compile(r'\bRPE\s+(\d+(?:\.\d+)?)\b', re.IGNORECASE)
_PACE_RE = re.compile(r'@\s*(\d+:\d{2})\s*/?\s*km\b', re.IGNORECASE)
_PACE_ZONE_RE = re.compile(r'@\s*Z([1-5])\b', re.IGNORECASE)


def _sign_to_direction(sign: str) -> str:
    s = sign.strip()
    if s in ('+-', '-+', '±'):
        return 'round_trip'
    if s == '-':
        return 'down'
    return 'up'


def text_to_steps(text: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse PaceMind workout syntax into a list of structured steps.

    Returns (steps, errors). errors is a list of {line: int, message: str}.
    The parser is lenient: it skips invalid lines and records errors but keeps
    going. Validation against the schema is left to validate_steps().
    """
    steps: List[Dict] = []
    errors: List[Dict] = []
    current_repeat: Optional[Dict] = None

    for line_no, raw in enumerate((text or '').splitlines(), start=1):
        if not raw.strip():
            continue
        if raw.lstrip().startswith('//'):
            continue

        is_indented = bool(raw) and raw[0] in (' ', '\t')
        content = raw.strip()

        # Repeat header
        m = _REPEAT_RE.match(content)
        if m:
            try:
                reps = int(m.group(1))
            except ValueError:
                errors.append({'line': line_no, 'message': 'invalid repeat count'})
                continue
            if reps < 1 or reps > MAX_REPEATS:
                errors.append({'line': line_no, 'message': f'repeats must be 1-{MAX_REPEATS}'})
                continue
            current_repeat = {'type': 'repeat', 'repeats': reps, 'steps': []}
            steps.append(current_repeat)
            continue

        try:
            step = _parse_step_line(content, inside_repeat=is_indented)
        except _ParseError as e:
            errors.append({'line': line_no, 'message': str(e)})
            continue

        if is_indented and current_repeat is not None:
            current_repeat['steps'].append(step)
        else:
            current_repeat = None
            steps.append(step)

    return steps, errors


class _ParseError(ValueError):
    pass


def _parse_step_line(content: str, inside_repeat: bool) -> Dict:
    """Parse a single non-repeat step line into a step dict."""
    remaining = content

    # Extract notes first (so they don't pollute other regexes)
    notes: Optional[str] = None
    nm = _NOTES_HASH_RE.search(remaining)
    if nm:
        notes = nm.group(1).strip() or None
        remaining = remaining[:nm.start()].strip()
    else:
        pm = _NOTES_PAREN_RE.search(remaining)
        if pm:
            notes = pm.group(1).strip() or None
            remaining = (remaining[:pm.start()] + remaining[pm.end():]).strip()

    step: Dict[str, Any] = {}

    # Elevation (must come before distance because both end in m)
    elev_match = _ELEV_PREFIX_RE.search(remaining)
    if elev_match:
        step['elevation_gain_m'] = float(elev_match.group(2))
        step['elevation_direction'] = _sign_to_direction(elev_match.group(1))
        remaining = (remaining[:elev_match.start()] + remaining[elev_match.end():]).strip()
    else:
        sm = _ELEV_SUFFIX_RE.search(remaining)
        if sm:
            step['elevation_gain_m'] = float(sm.group(1))
            step['elevation_direction'] = _sign_to_direction(sm.group(2))
            remaining = (remaining[:sm.start()] + remaining[sm.end():]).strip()

    # If no explicit elevation_direction, default by position (only set if elevation present)
    if 'elevation_gain_m' in step and 'elevation_direction' not in step:
        step['elevation_direction'] = 'up' if inside_repeat else 'round_trip'

    # Targets
    pace_m = _PACE_RE.search(remaining)
    if pace_m:
        step['target'] = {'type': 'pace', 'zone': f"{pace_m.group(1)}/km"}
        remaining = (remaining[:pace_m.start()] + remaining[pace_m.end():]).strip()
    else:
        pz = _PACE_ZONE_RE.search(remaining)
        if pz:
            step['target'] = {'type': 'pace', 'zone': f"Z{pz.group(1)}"}
            remaining = (remaining[:pz.start()] + remaining[pz.end():]).strip()

    if 'target' not in step:
        rpe_m = _RPE_RE.search(remaining)
        if rpe_m:
            step['target'] = {'type': 'effort', 'rpe': float(rpe_m.group(1))}
            remaining = (remaining[:rpe_m.start()] + remaining[rpe_m.end():]).strip()
        else:
            hr_m = _HR_ZONE_RE.search(remaining)
            if hr_m:
                step['target'] = {'type': 'hr', 'zone': int(hr_m.group(1))}
                remaining = (remaining[:hr_m.start()] + remaining[hr_m.end():]).strip()

    # Terrain
    tm = _TERRAIN_RE.search(remaining)
    if tm:
        terrain_word = tm.group(1).lower()
        terrain = _TERRAIN_ALIASES.get(terrain_word)
        if terrain:
            step['terrain'] = terrain
            remaining = (remaining[:tm.start()] + remaining[tm.end():]).strip()

    # Duration: hours form, then minutes, then seconds
    dh = _DURATION_HOURS_RE.search(remaining)
    if dh:
        hours = int(dh.group(1))
        mins = int(dh.group(2)) if dh.group(2) else 0
        step['duration_min'] = hours * 60 + mins
        remaining = (remaining[:dh.start()] + remaining[dh.end():]).strip()
    else:
        dm = _DURATION_MIN_RE.search(remaining)
        if dm:
            step['duration_min'] = float(dm.group(1))
            remaining = (remaining[:dm.start()] + remaining[dm.end():]).strip()
        else:
            ds = _DURATION_SEC_RE.search(remaining)
            if ds:
                step['duration_min'] = round(int(ds.group(1)) / 60, 2)
                remaining = (remaining[:ds.start()] + remaining[ds.end():]).strip()

    # Distance: km then m
    dkm = _DISTANCE_KM_RE.search(remaining)
    if dkm:
        step['distance_m'] = float(dkm.group(1)) * 1000
        remaining = (remaining[:dkm.start()] + remaining[dkm.end():]).strip()
    else:
        dmt = _DISTANCE_M_RE.search(remaining)
        if dmt:
            step['distance_m'] = float(dmt.group(1))
            remaining = (remaining[:dmt.start()] + remaining[dmt.end():]).strip()

    # Step type from leading word, default work
    step_type = 'work'
    leading = remaining.split(None, 1)
    if leading:
        head = leading[0].lower().rstrip(':,')
        mapped = _KEYWORD_TO_TYPE.get(head)
        if mapped:
            step_type = mapped
    step['type'] = step_type

    if notes:
        step['notes'] = notes

    # Sanity: every non-repeat step must have at least one measure
    if not any(step.get(k) for k in ('duration_min', 'distance_m', 'elevation_gain_m')):
        raise _ParseError('step needs a duration, distance, or elevation')

    return step


# ---------------------------------------------------------------------------
# Time prediction (physics-based) for steps
# ---------------------------------------------------------------------------

# Defaults mirror physics_model.calibration.DEFAULT_PARAMS
_DEFAULT_PHYSICS = {
    'v_flat': 3.33,        # m/s -- ~5:00 min/km
    'k_up': 1.0,
    'k_tech': 1.0,
    'a_param': 3.0,
    'k_terrain_up': 1.08,
    'k_terrain_down': 1.12,
}


def _resolve_direction(step: Dict, inside_repeat: bool) -> str:
    direction = step.get('elevation_direction')
    if direction in VALID_ELEV_DIRECTIONS:
        return direction
    return 'up' if inside_repeat else 'round_trip'


def _predict_velocity(grade: float, params: Dict, going_down: bool) -> float:
    """Wrap physics_model predictors with sensible defaults."""
    from services.physics_model.core import predict_uphill_velocity, predict_downhill_velocity
    grade = max(-0.30, min(0.30, grade))
    v_flat = params.get('v_flat') or _DEFAULT_PHYSICS['v_flat']
    k_up = params.get('k_up', _DEFAULT_PHYSICS['k_up'])
    k_terrain_up = params.get('k_terrain_up', _DEFAULT_PHYSICS['k_terrain_up'])
    if going_down:
        return predict_downhill_velocity(
            grade=-abs(grade),
            v_flat=v_flat,
            k_tech=params.get('k_tech', _DEFAULT_PHYSICS['k_tech']),
            a_param=params.get('a_param', _DEFAULT_PHYSICS['a_param']),
            k_terrain_down=params.get('k_terrain_down', _DEFAULT_PHYSICS['k_terrain_down']),
            k_terrain_up=k_terrain_up,
            fatigue_factor=1.0,
            k_up=k_up,
        )
    return predict_uphill_velocity(
        grade=max(0.0, grade),
        v_flat=v_flat,
        k_up=k_up,
        k_terrain=k_terrain_up,
        fatigue_factor=1.0,
    )


def predict_step_duration_min(step: Dict, params: Optional[Dict], inside_repeat: bool = False) -> Optional[float]:
    """Predict duration_min for a non-repeat step from distance + elevation.

    - If the step has explicit duration_min, return it.
    - If only duration is implied (no distance), return None.
    - Otherwise: use physics model with the user's params (or defaults).
      direction is derived from explicit elevation_direction or positional rule.
    """
    if step.get('type') == 'repeat':
        return None
    if step.get('duration_min'):
        return float(step['duration_min'])
    distance_m = step.get('distance_m') or 0
    if distance_m <= 0:
        return None

    physics = {**_DEFAULT_PHYSICS, **(params or {})}
    elev = step.get('elevation_gain_m') or 0
    direction = _resolve_direction(step, inside_repeat) if elev else 'up'

    if elev <= 0 or direction == 'up':
        grade = (elev / distance_m) if distance_m else 0.0
        v = _predict_velocity(grade, physics, going_down=False)
        seconds = distance_m / max(v, 0.01)
        return round(seconds / 60.0, 1)

    if direction == 'down':
        grade = elev / distance_m
        v = _predict_velocity(grade, physics, going_down=True)
        seconds = distance_m / max(v, 0.01)
        return round(seconds / 60.0, 1)

    # round_trip: half up, half down, equal elevation gain == loss
    half_dist = distance_m / 2.0
    grade_up = elev / half_dist if half_dist else 0.0
    grade_down = elev / half_dist if half_dist else 0.0
    v_up = _predict_velocity(grade_up, physics, going_down=False)
    v_down = _predict_velocity(grade_down, physics, going_down=True)
    seconds = half_dist / max(v_up, 0.01) + half_dist / max(v_down, 0.01)
    return round(seconds / 60.0, 1)


def predict_steps_durations(steps: List[Dict], params: Optional[Dict], _inside_repeat: bool = False) -> List[Dict]:
    """Return a new steps list with duration_min auto-filled where missing.

    Existing duration_min values are preserved. For repeats, recurses on children
    with inside_repeat=True so the positional rule resolves correctly.
    """
    out: List[Dict] = []
    for step in steps:
        new_step = dict(step)
        if step.get('type') == 'repeat':
            new_step['steps'] = predict_steps_durations(step.get('steps', []), params, _inside_repeat=True)
        elif not new_step.get('duration_min'):
            predicted = predict_step_duration_min(new_step, params, inside_repeat=_inside_repeat)
            if predicted is not None:
                new_step['duration_min'] = predicted
                new_step['duration_predicted'] = True
        out.append(new_step)
    return out

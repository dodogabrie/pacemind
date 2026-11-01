"""Calendar export service - generates ICS files from training plans."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional


# Day name to weekday offset (Monday=0)
DAY_TO_OFFSET = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6,
}


def _escape_ics(text: str) -> str:
    """Escape text for ICS format."""
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _format_dt(dt: datetime) -> str:
    """Format datetime for ICS (DATE only for all-day events)."""
    return dt.strftime('%Y%m%d')


def plan_start(plan):
    """Monday of the week the plan was created: week 1 starts there."""
    created = plan.created_at or datetime.now(timezone.utc)
    if isinstance(created, datetime):
        created = created.date()
    return created - timedelta(days=created.weekday())


def iter_workout_days(plan, plan_start_date=None):
    """Yield (date, week, day) for every non-rest day of the plan."""
    plan_start_date = plan_start_date or plan_start(plan)
    for week in (plan.weeks or []):
        week_start = plan_start_date + timedelta(weeks=week.get('week_number', 1) - 1)
        for day_data in week.get('days', []):
            offset = DAY_TO_OFFSET.get(day_data.get('day', ''))
            if offset is None or day_data.get('workout_type', 'easy') == 'rest':
                continue
            # Saved plans carry their own dates (anchored to the race); the
            # created-at Monday is only a fallback for undated legacy plans.
            try:
                yield date.fromisoformat(str(day_data['date'])[:10]), week, day_data
            except (KeyError, TypeError, ValueError):
                yield week_start + timedelta(days=offset), week, day_data


def generate_ics(plan, plan_start_date: Optional[datetime] = None) -> str:
    """Generate an ICS calendar string from a training plan.

    Args:
        plan: TrainingPlan object with .weeks, .plan_name, .race_date
        plan_start_date: Override for plan start date (defaults to created_at Monday)

    Returns:
        ICS file content as string
    """
    plan_start_date = plan_start_date or plan_start(plan)

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//PaceMind//Training Plan//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{_escape_ics(plan.plan_name)}',
    ]

    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    for event_date, week, day_data in iter_workout_days(plan, plan_start_date):
        week_number = week.get('week_number', 1)
        day_name = day_data.get('day', '')
        workout_type = day_data.get('workout_type', 'easy')
        title = day_data.get('title', workout_type.replace('_', ' ').title())

        # Build description
        desc_parts = []
        if day_data.get('distance_km'):
            desc_parts.append(f"Distance: {day_data['distance_km']} km")
        if day_data.get('elevation_m'):
            desc_parts.append(f"Elevation: {day_data['elevation_m']} m")
        if day_data.get('duration_min'):
            desc_parts.append(f"Duration: {day_data['duration_min']} min")
        if day_data.get('steps'):
            from services.workout_service import steps_to_text
            steps_text = steps_to_text(day_data['steps'])
            desc_parts.append(f"Workout:\\n{steps_text}")
        if day_data.get('notes'):
            desc_parts.append(f"Notes: {day_data['notes']}")
        desc_parts.append(f"Type: {workout_type}")
        desc_parts.append(f"Week {week_number}: {week.get('theme', '')}")
        description = '\\n'.join(desc_parts)

        # Type badge in title
        type_badges = {
            'easy': 'Easy', 'tempo': 'Tempo', 'intervals': 'Intervals',
            'long_run': 'Long Run', 'hill_repeats': 'Hills',
            'cross_train': 'Cross', 'recovery': 'Recovery',
            'vert_session': 'Vert', 'back_to_back': 'B2B',
            'race_simulation': 'Race Sim',
        }
        badge = type_badges.get(workout_type, '')
        full_title = f"[{badge}] {title}" if badge else title

        # Duration for DTEND (use duration_min if available, else 60min default)
        duration_min = day_data.get('duration_min', 60)

        # Use VEVENT with all-day event
        uid = f"plan-{plan.id}-w{week_number}-{day_name}@gpxanalyzer"
        next_day = event_date + timedelta(days=1)

        lines.extend([
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{now}',
            f'DTSTART;VALUE=DATE:{_format_dt(event_date)}',
            f'DTEND;VALUE=DATE:{_format_dt(next_day)}',
            f'SUMMARY:{_escape_ics(full_title)}',
            f'DESCRIPTION:{_escape_ics(description)}',
            # 30min reminder
            'BEGIN:VALARM',
            'TRIGGER:-PT30M',
            'ACTION:DISPLAY',
            f'DESCRIPTION:Workout: {_escape_ics(title)}',
            'END:VALARM',
            'END:VEVENT',
        ])

    # Add race day event if race_date exists
    if plan.race_date:
        race_date = plan.race_date
        if isinstance(race_date, datetime):
            race_date = race_date.date()
        next_day = race_date + timedelta(days=1)
        lines.extend([
            'BEGIN:VEVENT',
            f'UID:plan-{plan.id}-raceday@gpxanalyzer',
            f'DTSTAMP:{now}',
            f'DTSTART;VALUE=DATE:{_format_dt(race_date)}',
            f'DTEND;VALUE=DATE:{_format_dt(next_day)}',
            f'SUMMARY:RACE DAY - {_escape_ics(plan.plan_name)}',
            f'DESCRIPTION:Race day! Good luck!',
            'BEGIN:VALARM',
            'TRIGGER:-P1D',
            'ACTION:DISPLAY',
            'DESCRIPTION:Race day tomorrow!',
            'END:VALARM',
            'END:VEVENT',
        ])

    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines)


# ── intervals.icu ──────────────────────────────────────────────────────────
# intervals.icu parses a workout description written in its own text syntax
# into a structured workout, then syncs it to Garmin and other watches.

def _icu_target(target: Optional[dict]) -> str:
    if not target or not target.get('zone') and target.get('type') != 'effort':
        return ''
    t, zone = target.get('type'), target.get('zone')
    if t == 'hr':
        return f' Z{zone} HR'
    if t == 'power':
        return f' Z{zone}'
    if t == 'pace':
        if isinstance(zone, str) and ':' in zone:
            return f" {zone.replace('/km', '')}/km Pace"
        return f' {zone} Pace'
    if t == 'effort' and target.get('rpe'):
        return f" RPE {target['rpe']}"  # no RPE target there: shown as a cue
    return ''


def _icu_step(step: dict) -> Optional[str]:
    if step.get('duration_min'):
        m = float(step['duration_min'])
        measure = f'{m:g}m' if m >= 1 else f'{round(m * 60)}s'
    elif step.get('distance_m'):
        measure = f"{step['distance_m'] / 1000:g}km"
    else:
        # ponytail: elevation-only steps have no intervals.icu measure; they
        # become a lap-button step. Map to an estimated time if users ask.
        return f"- lap +{step.get('elevation_gain_m', 0):g}m D+{_icu_target(step.get('target'))}"
    return f"- {measure}{_icu_target(step.get('target'))}"


_ICU_HEADERS = {'warmup': 'Warmup', 'cooldown': 'Cooldown'}


def steps_to_icu(steps: list) -> str:
    """Render PaceMind steps in intervals.icu workout syntax."""
    blocks = []
    for step in steps:
        if step.get('type') == 'repeat':
            lines = [f"{step.get('repeats', 1)}x"]
            lines += [l for l in map(_icu_step, step.get('steps', [])) if l]
        else:
            lines = [_icu_step(step)]
            header = _ICU_HEADERS.get(step.get('type'))
            if header:
                lines.insert(0, header)
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def plan_to_icu_events(plan) -> list:
    """intervals.icu events (bulk upsert payload) for every workout day."""
    events = []
    for event_date, week, day in iter_workout_days(plan):
        parts = [day['notes']] if day.get('notes') else []
        if day.get('steps'):
            parts.append(steps_to_icu(day['steps']))
        elif day.get('workout_type') == 'race_simulation':
            pass  # race day: an all-Z2 step would set the wrong HR alerts on the watch
        elif day.get('duration_min'):
            parts.append(f"- {float(day['duration_min']):g}m Z2 HR")
        elif day.get('distance_km'):
            parts.append(f"- {float(day['distance_km']):g}km Z2 HR")
        event = {
            'category': 'WORKOUT',
            'type': 'Run',
            'start_date_local': f'{event_date.isoformat()}T00:00:00',
            'name': day.get('title') or day.get('workout_type', 'Run').replace('_', ' ').title(),
            'description': '\n\n'.join(parts),
            'external_id': f"pacemind-{plan.id}-w{week.get('week_number', 1)}-{day.get('day')}",
        }
        if day.get('duration_min'):
            event['moving_time'] = int(float(day['duration_min']) * 60)
        events.append(event)
    return events

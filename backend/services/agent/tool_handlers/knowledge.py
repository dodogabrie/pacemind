"""Coaching knowledge lookup and training readiness assessment handlers."""

import json as _json
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path as _Path

from config.hybrid_config import get_logger
from models import Activity
from repositories import UserLearnedParamsRepository

logger = get_logger(__name__)

_KNOWLEDGE_DIR = _Path(__file__).resolve().parent.parent.parent.parent / 'data' / 'coaching_knowledge'
_knowledge_index_cache = None


def _load_knowledge_index():
    """Load and cache the coaching knowledge index."""
    global _knowledge_index_cache
    if _knowledge_index_cache is not None:
        return _knowledge_index_cache
    index_path = _KNOWLEDGE_DIR / '_index.json'
    if not index_path.exists():
        return {'topics': {}}
    with open(index_path, 'r') as f:
        _knowledge_index_cache = _json.load(f)
    return _knowledge_index_cache


def _filter_sections(content: str, query_context: str, max_chars: int = 8000) -> str:
    """If content exceeds max_chars, filter to the most relevant ## sections."""
    if len(content) <= max_chars or not query_context:
        return content[:max_chars]

    query_words = set(query_context.lower().split())
    sections = []
    current_header = ''
    current_body = []

    for line in content.split('\n'):
        if line.startswith('## '):
            if current_header:
                sections.append((current_header, '\n'.join(current_body)))
            current_header = line
            current_body = []
        else:
            current_body.append(line)

    if current_header:
        sections.append((current_header, '\n'.join(current_body)))

    # Score each section by keyword overlap
    scored = []
    for header, body in sections:
        text_lower = (header + ' ' + body).lower()
        score = sum(1 for w in query_words if w in text_lower)
        scored.append((score, header, body))

    # Always include Key Principles + Decision Rules, then top scored
    result_parts = []
    remaining = []
    for score, header, body in scored:
        if 'Key Principles' in header or 'Decision Rules' in header:
            result_parts.append(header + '\n' + body)
        else:
            remaining.append((score, header, body))

    remaining.sort(key=lambda x: -x[0])
    for score, header, body in remaining:
        candidate = header + '\n' + body
        if sum(len(p) for p in result_parts) + len(candidate) <= max_chars:
            result_parts.append(candidate)

    return '\n\n'.join(result_parts)[:max_chars]


def _handle_lookup_coaching_knowledge(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Look up coaching knowledge from reference files."""
    topics = tool_input.get('topics', [])
    query_context = tool_input.get('query_context', '')

    if not topics:
        return {'error': 'No topics specified. Available: aerobic_base, intensity_zones, '
                'periodization, strength_training, uphill_training, recovery, '
                'mental_toughness, weekly_structure, race_pacing, ultra_strategy, '
                'nutrition_racing, nutrition_daily'}

    index = _load_knowledge_index()
    results = {}

    for topic in topics[:3]:  # Max 3 topics per call
        if topic not in index.get('topics', {}):
            results[topic] = {'error': f'Unknown topic: {topic}. Available: {", ".join(index["topics"].keys())}'}
            continue

        topic_info = index['topics'][topic]
        file_path = _KNOWLEDGE_DIR / topic_info['file']

        if not file_path.exists():
            results[topic] = {'error': f'Knowledge file not found: {topic_info["file"]}'}
            continue

        with open(file_path, 'r') as f:
            content = f.read()

        filtered = _filter_sections(content, query_context)
        results[topic] = {
            'content': filtered,
            'description': topic_info['description'],
        }

    return {
        'knowledge': results,
        'topics_loaded': list(results.keys()),
        'note': (
            'Internal coaching reference. Apply these protocols as your own '
            'coaching judgement — speak in first person. Never tell the user '
            'the advice comes from a book, manual, chapter, section, or '
            'external source. The user should perceive you as the coach, '
            'not as a citation engine.'
        ),
    }


def _handle_assess_training_readiness(tool_input: Dict, user_id: int) -> Dict:
    """Assess training readiness using endurance-training criteria.

    Classifies athlete as Cat 1 (base building) or Cat 2 (can add specificity)
    based on annual training hours, consistency, and ADS risk. Checks volume
    trends and readiness vs target race.
    """
    from collections import defaultdict

    target_distance_km = tool_input.get('target_race_distance_km')
    target_elevation_m = tool_input.get('target_race_elevation_m')

    # --- 1. Get last 12 weeks of Strava activities ---
    weeks_to_analyze = 12
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks_to_analyze)

    activities = (
        Activity.query
        .filter(Activity.user_id == user_id)
        .filter(Activity.start_date >= cutoff)
        .order_by(Activity.start_date.asc())
        .all()
    )

    if not activities:
        return {
            'error': 'No Strava activities found in the last 12 weeks. '
                     'Connect Strava and sync activities first.',
            'athlete_category': 'cat_1',
            'category_reasoning': 'No training data available — default to base building.',
            'recommendations': [
                'Connect your Strava account and sync your activities.',
                'Start with a consistent base of 3-4 easy runs per week.',
                'Focus on building the habit before adding intensity.',
            ],
            'suggested_templates': ['cat1_base_12w'],
        }

    # --- 2. Group by ISO week ---
    weekly = defaultdict(list)
    for act in activities:
        iso_year, iso_week, _ = act.start_date.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        weekly[key].append(act)

    # --- 3. Per-week metrics ---
    week_keys = sorted(weekly.keys())
    week_metrics = []

    for week_key in week_keys:
        acts = weekly[week_key]
        total_km = sum((a.distance or 0) / 1000 for a in acts)
        total_hours = 0.0
        total_elevation = 0.0
        longest_km = 0.0

        for a in acts:
            dist_km = (a.distance or 0) / 1000
            if dist_km > longest_km:
                longest_km = dist_km

            # Extract duration from streams if available
            streams = a.streams
            if streams and isinstance(streams, dict):
                time_data = streams.get('time')
                if time_data:
                    t_list = time_data if isinstance(time_data, list) else time_data.get('data', [])
                    if t_list:
                        total_hours += t_list[-1] / 3600.0

                # Extract elevation gain from altitude stream
                alt_data = streams.get('altitude')
                if alt_data:
                    alt_list = alt_data if isinstance(alt_data, list) else alt_data.get('data', [])
                    for i in range(1, len(alt_list)):
                        diff = alt_list[i] - alt_list[i - 1]
                        if diff > 0:
                            total_elevation += diff
            else:
                # Estimate duration from distance (assume ~6:00/km avg)
                total_hours += dist_km * 6.0 / 60.0

        week_metrics.append({
            'week': week_key,
            'activity_count': len(acts),
            'total_km': round(total_km, 1),
            'total_hours': round(total_hours, 2),
            'total_elevation_m': round(total_elevation, 0),
            'longest_km': round(longest_km, 1),
        })

    # --- 4. Aggregate statistics ---
    total_weeks = len(week_metrics)
    avg_weekly_hours = sum(w['total_hours'] for w in week_metrics) / total_weeks if total_weeks else 0
    avg_weekly_km = sum(w['total_km'] for w in week_metrics) / total_weeks if total_weeks else 0
    avg_weekly_elevation = sum(w['total_elevation_m'] for w in week_metrics) / total_weeks if total_weeks else 0
    estimated_annual_hours = avg_weekly_hours * 50  # ~50 training weeks/year

    # Consistency: weeks with 3+ activities
    weeks_active = sum(1 for w in week_metrics if w['activity_count'] >= 3)
    consistency_pct = round(weeks_active / total_weeks * 100, 1) if total_weeks else 0

    # Longest recent run (across all weeks)
    longest_recent_run_km = max(w['longest_km'] for w in week_metrics) if week_metrics else 0

    # --- 5. Volume trend (last 4 weeks vs previous 4 weeks) ---
    if total_weeks >= 8:
        recent_4 = week_metrics[-4:]
        previous_4 = week_metrics[-8:-4]
        recent_avg = sum(w['total_km'] for w in recent_4) / 4
        previous_avg = sum(w['total_km'] for w in previous_4) / 4
        if previous_avg > 0:
            change_pct = (recent_avg - previous_avg) / previous_avg * 100
            if change_pct > 10:
                volume_trend = 'increasing'
            elif change_pct < -10:
                volume_trend = 'declining'
            else:
                volume_trend = 'stable'
        else:
            volume_trend = 'increasing' if recent_avg > 0 else 'stable'
    elif total_weeks >= 4:
        half = total_weeks // 2
        recent = week_metrics[-half:]
        previous = week_metrics[:half]
        recent_avg = sum(w['total_km'] for w in recent) / len(recent)
        previous_avg = sum(w['total_km'] for w in previous) / len(previous)
        if previous_avg > 0:
            change_pct = (recent_avg - previous_avg) / previous_avg * 100
            if change_pct > 10:
                volume_trend = 'increasing'
            elif change_pct < -10:
                volume_trend = 'declining'
            else:
                volume_trend = 'stable'
        else:
            volume_trend = 'stable'
    else:
        volume_trend = 'insufficient_data'

    # --- 6. Check for learned params (physics model calibration) ---
    params_repo = UserLearnedParamsRepository()
    learned = params_repo.find_one_by(user_id=user_id)
    has_learned_params = learned is not None
    flat_speed_ms = None
    if has_learned_params and learned.v_flat:
        flat_speed_ms = learned.v_flat

    # --- 7. Cat 1 vs Cat 2 classification ---
    category_reasons = []

    if estimated_annual_hours < 400:
        athlete_category = 'cat_1'
        category_reasons.append(
            f'Estimated {estimated_annual_hours:.0f} hrs/year (< 400 threshold for Cat 2)'
        )
    elif consistency_pct < 60:
        athlete_category = 'cat_1'
        category_reasons.append(
            f'Training consistency is {consistency_pct:.0f}% '
            f'({weeks_active}/{total_weeks} weeks with 3+ sessions) — '
            f'needs more consistent base before adding specificity'
        )
    else:
        athlete_category = 'cat_2'
        category_reasons.append(
            f'Estimated {estimated_annual_hours:.0f} hrs/year (>= 400) '
            f'with {consistency_pct:.0f}% consistency'
        )

    # --- 8. ADS risk assessment ---
    if avg_weekly_hours < 6:
        if avg_weekly_km > 0 and longest_recent_run_km < avg_weekly_km * 0.4:
            ads_risk = 'likely'
            ads_reasoning = (
                f'Low weekly volume ({avg_weekly_hours:.1f} hrs/week) with no long runs '
                f'relative to total volume suggests insufficient aerobic base. '
                f'Most training may be at too high an intensity.'
            )
        else:
            ads_risk = 'possible'
            ads_reasoning = (
                f'Weekly hours ({avg_weekly_hours:.1f}) are below the 6-8 hr/week '
                f'threshold where ADS is common. Build easy volume before adding intensity.'
            )
    elif not has_learned_params:
        ads_risk = 'possible'
        ads_reasoning = (
            'No calibration data yet — cannot assess aerobic efficiency. '
            'Sync more activities and run a calibration to evaluate.'
        )
    else:
        ads_risk = 'unlikely'
        ads_reasoning = (
            f'Training volume ({avg_weekly_hours:.1f} hrs/week) is adequate. '
        )
        if flat_speed_ms:
            ads_reasoning += (
                f'Calibrated flat speed: {flat_speed_ms:.2f} m/s '
                '({}:{:02d} min/km).'.format(*divmod(round(1000 / flat_speed_ms), 60))
            )

    # --- 9. Generate recommendations ---
    recommendations = []

    if athlete_category == 'cat_1':
        recommendations.append(
            'Focus on building aerobic base: 80%+ of training at easy/conversational pace (Z1-Z2).'
        )
        recommendations.append(
            f'Target gradual volume increase: aim for {max(avg_weekly_hours * 1.1, 4):.0f}-'
            f'{max(avg_weekly_hours * 1.3, 6):.0f} hrs/week over the next 8 weeks.'
        )
        if consistency_pct < 60:
            recommendations.append(
                'Prioritize consistency: aim for at least 3 sessions/week before increasing intensity.'
            )
    else:
        recommendations.append(
            'You have a solid aerobic base. Consider adding structured intensity: '
            '1-2 quality sessions per week (tempo, intervals, or hill repeats).'
        )

    if ads_risk in ('likely', 'possible'):
        recommendations.append(
            'ADS concern: ensure most runs are truly easy (can hold a conversation). '
            'Add a weekly MAF-style test to track aerobic progress.'
        )

    if volume_trend == 'declining':
        recommendations.append(
            'Your volume is declining — check for fatigue or scheduling issues. '
            'Maintain current volume before building further.'
        )

    # Race readiness
    if target_distance_km:
        if target_distance_km <= 21.1:
            min_long_run_pct = 0.5
        elif target_distance_km <= 42.2:
            min_long_run_pct = 0.4
        else:
            min_long_run_pct = 0.3

        needed_long_run = target_distance_km * min_long_run_pct
        if longest_recent_run_km < needed_long_run:
            recommendations.append(
                f'Your longest recent run ({longest_recent_run_km:.1f} km) is below the '
                f'recommended {min_long_run_pct * 100:.0f}% of race distance '
                f'({needed_long_run:.1f} km). Build long run progressively.'
            )

    if target_elevation_m and avg_weekly_elevation > 0:
        # Peak weekly elevation should reach 50-80% of race D+
        needed_weekly_elev = target_elevation_m * 0.5
        if avg_weekly_elevation < needed_weekly_elev:
            recommendations.append(
                f'Average weekly elevation ({avg_weekly_elevation:.0f} m) is below the '
                f'recommended 50% of race D+ ({needed_weekly_elev:.0f} m). '
                f'Add more hill work and vert sessions.'
            )

    # Cap at 5 recommendations
    recommendations = recommendations[:5]

    # --- 10. Suggest templates ---
    suggested_templates = []
    if athlete_category == 'cat_1':
        suggested_templates.append('cat1_base_12w')

    if target_distance_km:
        if target_distance_km <= 10:
            suggested_templates.append('vk_race_8w')
        elif target_distance_km <= 21.1:
            suggested_templates.append('trail_half_marathon_8w')
        elif target_distance_km <= 35:
            if target_elevation_m and target_elevation_m > 1500:
                suggested_templates.append('skyrace_30k_10w')
            else:
                suggested_templates.append('trail_30k_6w')
        elif target_distance_km <= 50:
            suggested_templates.append('trail_50k_10w')
        elif target_distance_km <= 80:
            suggested_templates.append('trail_80k_16w')
        elif target_distance_km <= 130:
            suggested_templates.append('trail_50mi_16w')
        else:
            suggested_templates.append('trail_100mi_24w')

    # De-duplicate while preserving order
    seen = set()
    unique_templates = []
    for t in suggested_templates:
        if t not in seen:
            seen.add(t)
            unique_templates.append(t)

    return {
        'athlete_category': athlete_category,
        'category_reasoning': '; '.join(category_reasons),
        'estimated_weekly_hours': round(avg_weekly_hours, 1),
        'estimated_annual_hours': round(estimated_annual_hours, 0),
        'training_consistency': {
            'weeks_active': weeks_active,
            'weeks_analyzed': total_weeks,
            'pct': consistency_pct,
        },
        'volume_trend': volume_trend,
        'longest_recent_run_km': round(longest_recent_run_km, 1),
        'weekly_elevation_avg_m': round(avg_weekly_elevation, 0),
        'ads_risk': ads_risk,
        'ads_reasoning': ads_reasoning,
        'recommendations': recommendations,
        'suggested_templates': unique_templates,
        'has_learned_params': has_learned_params,
        'flat_speed_ms': round(flat_speed_ms, 2) if flat_speed_ms else None,
        'weekly_summary': week_metrics,
    }

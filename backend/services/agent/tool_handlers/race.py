"""Race-related handlers: profile, briefing, pacing, performance, reports."""

import statistics
from typing import Dict, Any
from datetime import datetime, timezone

from config.hybrid_config import get_logger
from models import UserActivityResidual
from repositories import GPXFileRepository
from services.hybrid_prediction_service import HybridPredictionService
from services.osm_terrain_service import OSMTerrainService
from services.weather_service import WeatherService
from services.training_load_service import TrainingLoadService
from services.agent.tool_handlers.validation import _get_gpx_points

logger = get_logger(__name__)


def _handle_get_race_profile(tool_input: Dict, user_id: int) -> Dict:
    """Analyze a target race GPX route in detail."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    # Basic stats
    total_distance_km = points[-1].get('distance', 0) / 1000
    elevation_gain = 0
    elevation_loss = 0
    grades = []
    for i in range(1, len(points)):
        elev_diff = points[i].get('elevation', 0) - points[i - 1].get('elevation', 0)
        dist_diff = points[i].get('distance', 0) - points[i - 1].get('distance', 0)
        if elev_diff > 0:
            elevation_gain += elev_diff
        else:
            elevation_loss += abs(elev_diff)
        if dist_diff > 0:
            grades.append(elev_diff / dist_diff)

    # Grade statistics
    avg_grade = statistics.mean(grades) if grades else 0
    max_grade = max(grades) if grades else 0
    min_grade = min(grades) if grades else 0
    steep_up_pct = len([g for g in grades if g > 0.15]) / len(grades) * 100 if grades else 0
    steep_down_pct = len([g for g in grades if g < -0.15]) / len(grades) * 100 if grades else 0

    # Difficulty rating
    difficulty_score = (elevation_gain / 100) + (total_distance_km * 2) + (steep_up_pct * 0.5)
    if difficulty_score < 30:
        difficulty = 'easy'
    elif difficulty_score < 60:
        difficulty = 'moderate'
    elif difficulty_score < 100:
        difficulty = 'hard'
    else:
        difficulty = 'ultra'

    # Terrain analysis
    terrain_desc = None
    try:
        terrain_service = OSMTerrainService()
        terrain_factors = terrain_service.get_terrain_for_route(points, bounds)
        terrain_summary = terrain_service.get_terrain_summary(terrain_factors)
        terrain_desc = terrain_service.describe_terrain(terrain_summary)
    except Exception:
        pass

    # Time estimate
    time_estimate = None
    try:
        prediction_service = HybridPredictionService()
        result = prediction_service.predict(user_id=user_id, gpx_points=points, effort='race')
        if 'total_time_seconds' in result:
            total_time = result['total_time_seconds']
            h = int(total_time // 3600)
            m = int((total_time % 3600) // 60)
            time_estimate = f"{h}:{m:02d}"
    except Exception:
        pass

    # Key sections analysis — identify the hardest parts of the race
    # Aggregate into ~1km windows to find sustained climbs/descents
    key_sections = []
    window_size_m = 1000
    i = 0
    while i < len(points) - 1:
        seg_start_dist = points[i].get('distance', 0)
        seg_start_elev = points[i].get('elevation', 0)
        j = i + 1
        while j < len(points) and (points[j].get('distance', 0) - seg_start_dist) < window_size_m:
            j += 1
        if j >= len(points):
            j = len(points) - 1
        seg_end_dist = points[j].get('distance', 0)
        seg_end_elev = points[j].get('elevation', 0)
        seg_dist_m = seg_end_dist - seg_start_dist
        if seg_dist_m > 100:
            seg_elev_diff = seg_end_elev - seg_start_elev
            seg_grade = seg_elev_diff / seg_dist_m

            # Find sustained steep climbs (>10% grade for 1km+)
            if seg_grade > 0.10:
                # Extend to find the full sustained climb
                end = j
                while end < len(points) - 1:
                    next_dist = points[end + 1].get('distance', 0) - points[end].get('distance', 0)
                    next_elev = points[end + 1].get('elevation', 0) - points[end].get('elevation', 0)
                    if next_dist > 0 and (next_elev / next_dist) > 0.05:
                        end += 1
                    else:
                        break
                total_climb_dist = (points[end].get('distance', 0) - seg_start_dist) / 1000
                total_climb_gain = points[end].get('elevation', 0) - seg_start_elev
                if total_climb_gain > 50:
                    key_sections.append({
                        'type': 'steep_climb',
                        'km_start': round(seg_start_dist / 1000, 1),
                        'km_end': round(points[end].get('distance', 0) / 1000, 1),
                        'distance_km': round(total_climb_dist, 1),
                        'elevation_gain_m': round(total_climb_gain),
                        'avg_grade_pct': round(total_climb_gain / (total_climb_dist * 1000) * 100, 1) if total_climb_dist > 0 else 0,
                        'training_note': f'Simulate with {total_climb_dist:.0f}km climb at {total_climb_gain / (total_climb_dist * 1000) * 100:.0f}% grade' if total_climb_dist > 0 else '',
                    })
                j = end

            # Find sustained steep descents (< -10% grade for 1km+)
            elif seg_grade < -0.10:
                end = j
                while end < len(points) - 1:
                    next_dist = points[end + 1].get('distance', 0) - points[end].get('distance', 0)
                    next_elev = points[end + 1].get('elevation', 0) - points[end].get('elevation', 0)
                    if next_dist > 0 and (next_elev / next_dist) < -0.05:
                        end += 1
                    else:
                        break
                total_desc_dist = (points[end].get('distance', 0) - seg_start_dist) / 1000
                total_desc_loss = abs(points[end].get('elevation', 0) - seg_start_elev)
                if total_desc_loss > 100:
                    key_sections.append({
                        'type': 'steep_descent',
                        'km_start': round(seg_start_dist / 1000, 1),
                        'km_end': round(points[end].get('distance', 0) / 1000, 1),
                        'distance_km': round(total_desc_dist, 1),
                        'elevation_loss_m': round(total_desc_loss),
                        'avg_grade_pct': round(-total_desc_loss / (total_desc_dist * 1000) * 100, 1) if total_desc_dist > 0 else 0,
                        'training_note': f'Train downhill technique and eccentric strength for {total_desc_dist:.0f}km descent at {total_desc_loss / (total_desc_dist * 1000) * 100:.0f}% grade' if total_desc_dist > 0 else '',
                    })
                j = end

            # Find long sustained climbs (>5% grade for 3km+)
            elif seg_grade > 0.05:
                end = j
                while end < len(points) - 1:
                    next_dist = points[end + 1].get('distance', 0) - points[end].get('distance', 0)
                    next_elev = points[end + 1].get('elevation', 0) - points[end].get('elevation', 0)
                    if next_dist > 0 and (next_elev / next_dist) > 0.03:
                        end += 1
                    else:
                        break
                total_climb_dist = (points[end].get('distance', 0) - seg_start_dist) / 1000
                total_climb_gain = points[end].get('elevation', 0) - seg_start_elev
                if total_climb_dist >= 3 and total_climb_gain > 100:
                    key_sections.append({
                        'type': 'long_climb',
                        'km_start': round(seg_start_dist / 1000, 1),
                        'km_end': round(points[end].get('distance', 0) / 1000, 1),
                        'distance_km': round(total_climb_dist, 1),
                        'elevation_gain_m': round(total_climb_gain),
                        'avg_grade_pct': round(total_climb_gain / (total_climb_dist * 1000) * 100, 1) if total_climb_dist > 0 else 0,
                        'training_note': f'Build muscular endurance with Z3 grinding for {total_climb_dist:.0f}km sustained climbs',
                    })
                j = end

        i = j if j > i else i + 1

    # Deduplicate overlapping sections, keep the most significant
    key_sections.sort(key=lambda s: s.get('elevation_gain_m', 0) or s.get('elevation_loss_m', 0), reverse=True)
    filtered = []
    used_ranges = []
    for section in key_sections:
        start = section['km_start']
        end = section['km_end']
        overlaps = any(s <= start <= e or s <= end <= e for s, e in used_ranges)
        if not overlaps:
            filtered.append(section)
            used_ranges.append((start, end))
        if len(filtered) >= 8:
            break
    filtered.sort(key=lambda s: s['km_start'])

    # Race profile classification
    balance_ratio = round(elevation_loss / elevation_gain, 2) if elevation_gain > 0 else 1.0
    if balance_ratio < 0.3:
        race_type = 'uphill_only'
    elif balance_ratio > 1.3:
        race_type = 'downhill_finish'
    else:
        race_type = 'loop'

    return {
        'gpx_id': gpx_id,
        'distance_km': round(total_distance_km, 2),
        'elevation_gain_m': round(elevation_gain, 0),
        'elevation_loss_m': round(elevation_loss, 0),
        'elevation_ratio_m_per_km': round(elevation_gain / total_distance_km, 1) if total_distance_km > 0 else 0,
        'race_type': race_type,
        'dplus_dminus_balance': balance_ratio,
        'grade_stats': {
            'avg_pct': round(avg_grade * 100, 1),
            'max_up_pct': round(max_grade * 100, 1),
            'max_down_pct': round(min_grade * 100, 1),
            'steep_uphill_pct': round(steep_up_pct, 1),
            'steep_downhill_pct': round(steep_down_pct, 1),
        },
        'key_sections': filtered,
        'difficulty': difficulty,
        'terrain': terrain_desc,
        'estimated_time': time_estimate,
    }


def _handle_get_race_briefing(tool_input: Dict, user_id: int) -> Dict:
    """Generate comprehensive pre-race briefing.

    Delegates to `services.race_brief_data.build_race_brief` so the agent
    tool and the PDF download endpoint share one data source.
    """
    from services.race_brief_data import build_race_brief
    return build_race_brief(
        user_id=user_id,
        gpx_id=tool_input.get('gpx_id'),
        race_date_str=tool_input.get('race_date'),
        effort=tool_input.get('effort', 'race'),
    )


def _handle_get_pacing_strategy(tool_input: Dict, user_id: int) -> Dict:
    """Generate pacing strategy with per-km target paces."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    effort = tool_input.get('effort', 'race')

    # Run prediction
    prediction_service = HybridPredictionService()
    result = prediction_service.predict(
        user_id=user_id,
        gpx_points=points,
        include_diagnostics=False,
        effort=effort,
    )

    if 'error' in result:
        return result

    segments = result.get('segments', [])
    if not segments:
        return {'error': 'No segments in prediction'}

    # Aggregate into 1km splits
    splits = []
    current_km = 0
    km_time = 0.0
    km_elevation_gain = 0.0
    km_elevation_loss = 0.0
    km_start_dist = 0.0

    for seg in segments:
        seg_km = seg.get('distance_m', 0) / 1000
        new_km = int(seg_km)

        if new_km > current_km and current_km > 0:
            # Emit split
            km_dist = seg.get('distance_m', 0) - km_start_dist
            pace = (km_time / 60) if km_dist > 0 else 0  # min/km approx

            splits.append({
                'km': current_km,
                'pace_min_km': round(pace, 2),
                'time_s': round(km_time, 1),
                'elevation_gain_m': round(km_elevation_gain, 0),
                'elevation_loss_m': round(km_elevation_loss, 0),
                'surface_type': seg.get('surface_type', 'unknown'),
            })
            km_time = 0.0
            km_elevation_gain = 0.0
            km_elevation_loss = 0.0
            km_start_dist = seg.get('distance_m', 0)
            current_km = new_km

        km_time += seg.get('time_s', 0)
        grade = seg.get('grade', 0)
        length = seg.get('length_m', 0)
        if grade > 0:
            km_elevation_gain += grade * length
        else:
            km_elevation_loss += abs(grade) * length

    # Final split
    if km_time > 0:
        pace = (km_time / 60)
        splits.append({
            'km': current_km + 1,
            'pace_min_km': round(pace, 2),
            'time_s': round(km_time, 1),
            'elevation_gain_m': round(km_elevation_gain, 0),
            'elevation_loss_m': round(km_elevation_loss, 0),
        })

    total_time = result.get('total_time_seconds', 0)
    h = int(total_time // 3600)
    m = int((total_time % 3600) // 60)
    s = int(total_time % 60)

    return {
        'total_time_formatted': f"{h}:{m:02d}:{s:02d}",
        'effort': effort,
        'splits': splits,
        'n_splits': len(splits),
        'gpx_id': gpx_id,
    }


def _handle_get_past_performance(tool_input: Dict, user_id: int) -> Dict:
    """Analyze user's historical performance to find strengths/weaknesses."""
    residuals = (
        UserActivityResidual.query
        .filter_by(user_id=user_id)
        .order_by(UserActivityResidual.activity_date.desc())
        .all()
    )

    if not residuals:
        return {'error': 'No activity history available for analysis'}

    # Analyze residuals by grade category
    uphill_residuals = []      # grade > 5%
    flat_residuals = []        # -2% to 2%
    downhill_residuals = []    # grade < -5%
    steep_up_residuals = []    # grade > 15%
    steep_down_residuals = []  # grade < -15%
    long_distance_residuals = []  # cum_distance > 20km

    for res in residuals:
        for seg in res.segments:
            grade = seg.get('grade_mean', 0)
            actual = seg.get('actual_pace_ratio', 1.0)
            physics = seg.get('physics_pace_ratio', 1.0)
            residual = actual / physics if physics > 0 else 1.0
            dist_km = seg.get('distance_m', 0) / 1000

            if residual < 0.5 or residual > 2.0:
                continue

            if grade > 0.15:
                steep_up_residuals.append(residual)
            elif grade > 0.05:
                uphill_residuals.append(residual)
            elif grade < -0.15:
                steep_down_residuals.append(residual)
            elif grade < -0.05:
                downhill_residuals.append(residual)
            else:
                flat_residuals.append(residual)

            if dist_km > 20:
                long_distance_residuals.append(residual)

    def avg_residual(lst):
        return round(sum(lst) / len(lst), 3) if lst else None

    def interpret(avg):
        if avg is None:
            return "insufficient data"
        if avg < 0.93:
            return "significantly faster than model (strong)"
        elif avg < 0.97:
            return "faster than model (strength)"
        elif avg < 1.03:
            return "matches model well"
        elif avg < 1.07:
            return "slower than model (weakness)"
        else:
            return "significantly slower than model (clear weakness)"

    analysis = {
        'flat': {'avg_residual': avg_residual(flat_residuals), 'n_segments': len(flat_residuals)},
        'uphill': {'avg_residual': avg_residual(uphill_residuals), 'n_segments': len(uphill_residuals)},
        'downhill': {'avg_residual': avg_residual(downhill_residuals), 'n_segments': len(downhill_residuals)},
        'steep_uphill': {'avg_residual': avg_residual(steep_up_residuals), 'n_segments': len(steep_up_residuals)},
        'steep_downhill': {'avg_residual': avg_residual(steep_down_residuals), 'n_segments': len(steep_down_residuals)},
        'late_race': {'avg_residual': avg_residual(long_distance_residuals), 'n_segments': len(long_distance_residuals)},
    }

    # Add interpretations
    for key, val in analysis.items():
        val['interpretation'] = interpret(val['avg_residual'])

    # Find strengths and weaknesses
    strengths = [k for k, v in analysis.items() if v['avg_residual'] and v['avg_residual'] < 0.97 and v['n_segments'] >= 10]
    weaknesses = [k for k, v in analysis.items() if v['avg_residual'] and v['avg_residual'] > 1.03 and v['n_segments'] >= 10]

    return {
        'analysis': analysis,
        'strengths': strengths,
        'weaknesses': weaknesses,
        'total_activities': len(residuals),
    }


def _generate_coaching_insights(report_data: Dict) -> list:
    """Analyze race report data and return coaching insights based on detected patterns.

    Each insight is a dict with keys: pattern, insight, recommendation.
    Detection is defensive — missing data causes individual patterns to be skipped.
    """
    insights: list[Dict[str, str]] = []

    split_comparison = report_data.get('split_comparison') or []
    actual_total = report_data.get('actual_total_seconds')

    if not split_comparison:
        return insights

    # Extract actual paces, filtering out missing values
    paces = [s['actual_pace'] for s in split_comparison if s.get('actual_pace')]
    if len(paces) < 3:
        return insights

    n = len(paces)
    third = max(1, n // 3)

    first_third_avg = sum(paces[:third]) / third
    last_third_avg = sum(paces[n - third:]) / third
    overall_avg = sum(paces) / n

    # 1. Positive split / went out too fast
    try:
        if first_third_avg > 0 and last_third_avg > first_third_avg * 1.10:
            insights.append({
                'pattern': 'positive_split',
                'insight': (
                    'You went out too fast. The three-thirds pacing strategy recommends '
                    'a conservative first third, steady middle, and pushing only in the '
                    'final third. Starting too fast depletes glycogen reserves and leads '
                    'to late-race collapse.'
                ),
                'recommendation': (
                    'Practice disciplined starts. In your next race, aim to run the first '
                    'third 5-10 seconds per km slower than goal pace.'
                ),
            })
    except (ZeroDivisionError, TypeError):
        pass

    # 2. Late-race pace collapse (hitting the wall)
    try:
        quarter = max(1, n // 4)
        last_quarter_avg = sum(paces[n - quarter:]) / quarter
        if overall_avg > 0 and last_quarter_avg > overall_avg * 1.30:
            insights.append({
                'pattern': 'late_race_collapse',
                'insight': (
                    'Significant late-race slowdown detected. Possible causes: glycogen '
                    'depletion (were you fueling 200-300 cal/hour?), muscular endurance '
                    'deficit (consider ME training with hill sprints and steep Z3 grinding), '
                    "or insufficient aerobic base (the 'vacuum cleaner' ran out)."
                ),
                'recommendation': (
                    'Review your fueling strategy, add muscular endurance work (hill sprints: '
                    '8-10 sec max power, 2 min rest; steep Z3 grinding: 20-40 min on 20-50% '
                    'grade), and ensure a solid aerobic base.'
                ),
            })
    except (ZeroDivisionError, TypeError):
        pass

    # 3. Strong negative split (good pacing)
    try:
        if first_third_avg > 0 and last_third_avg < first_third_avg * 0.95:
            insights.append({
                'pattern': 'negative_split',
                'insight': (
                    'Excellent pacing! You followed a smart conservative-start strategy and '
                    'had energy to push at the end. This is the hallmark of well-developed '
                    'aerobic capacity.'
                ),
                'recommendation': (
                    'Keep building on this strength. Your aerobic base and pacing discipline '
                    'are working well.'
                ),
            })
    except (ZeroDivisionError, TypeError):
        pass

    # 4. Elevation-related slowdown
    try:
        flat_paces = [
            s['actual_pace'] for s in split_comparison
            if s.get('actual_pace') and abs(s.get('grade', 0)) <= 3
        ]
        steep_paces = [
            s['actual_pace'] for s in split_comparison
            if s.get('actual_pace') and s.get('grade', 0) > 10
        ]
        if flat_paces and steep_paces:
            flat_avg = sum(flat_paces) / len(flat_paces)
            steep_avg = sum(steep_paces) / len(steep_paces)
            if flat_avg > 0 and steep_avg > flat_avg * 1.50:
                insights.append({
                    'pattern': 'elevation_slowdown',
                    'insight': (
                        'Your uphill pace dropped significantly more than expected from '
                        'gradient alone. This suggests muscular endurance could be improved. '
                        'Consider adding hill sprints (8-10 sec max power, 2 min rest) and '
                        'steep Z3 grinding (20-40 min on 20-50% grade) to your base period.'
                    ),
                    'recommendation': (
                        'Add 1-2 weekly hill-specific sessions: short max-power hill sprints '
                        'for neuromuscular power, and longer steep Z3 efforts for muscular '
                        'endurance.'
                    ),
                })
    except (ZeroDivisionError, TypeError):
        pass

    # 5. Duration-based fueling check
    try:
        if actual_total and actual_total > 4 * 3600:
            insights.append({
                'pattern': 'fueling_check',
                'insight': (
                    'For efforts over 4 hours, fueling becomes critical. Aim for 200-300 '
                    'calories per hour with a mix of simple carbs and, at conversational '
                    'pace, real food. Post-race, consume 100-200 calories within 30 minutes '
                    '(3:1 carb:protein ratio) to speed recovery.'
                ),
                'recommendation': (
                    'Create a fueling plan: set alarms every 30-45 minutes, alternate '
                    'between gels/chews and real food, and practice this in long training runs.'
                ),
            })
    except (TypeError, ValueError):
        pass

    return insights


def _handle_generate_race_report(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Generate post-race analysis report."""
    plan_id = tool_input.get('plan_id')
    strava_activity_id = tool_input.get('strava_activity_id')

    if not plan_id or not strava_activity_id:
        return {'error': 'Both plan_id and strava_activity_id are required.'}

    from services.race_report_service import RaceReportService
    service = RaceReportService()
    report = service.generate_report(plan_id, strava_activity_id, user_id)

    # Append coaching insights if the report was generated successfully
    if 'error' not in report:
        report['coaching_insights'] = _generate_coaching_insights(report)

    return report


def _handle_get_race_report(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Retrieve existing race report."""
    plan_id = tool_input.get('plan_id')
    if not plan_id:
        return {'error': 'plan_id is required.'}

    from services.race_report_service import RaceReportService
    service = RaceReportService()
    return service.get_report(plan_id, user_id)


def _handle_find_race_online(tool_input: Dict, user_id: int) -> Dict[str, Any]:
    """Calendar first, then web discovery; optionally import the GPX for the user."""
    from datetime import date

    from models import Race
    from services.race_discovery_service import discover_race, import_race_gpx

    query = (tool_input.get('query') or '').strip()
    if len(query) < 3:
        return {'error': 'query is required'}
    races = []
    if not tool_input.get('refresh'):
        words = [w for w in query.split() if len(w) > 3][:3]
        q = Race.query.filter(Race.date >= date.today())
        for w in words:
            q = q.filter(Race.name.ilike(f'%{w}%') | Race.location.ilike(f'%{w}%'))
        races = q.order_by(Race.date).limit(6).all() if words else []
    source = 'calendar' if races else 'web'
    if not races:
        try:
            races = discover_race(query)
        except Exception as e:  # noqa: BLE001 - network/LLM failure must not break the chat
            logger.warning('find_race_online failed for %r: %s', query, e)
            return {'error': 'online search failed, retry later', 'found': False}
    out = []
    for r in races:
        d = r.to_dict()
        item = {k: d[k] for k in ('id', 'name', 'date', 'date_estimated', 'location', 'distance_km',
                                  'elev_gain_m', 'race_type', 'url', 'description', 'has_poster', 'has_gpx')}
        if tool_input.get('import_gpx') and r.has_gpx:
            item['gpx_id'] = import_race_gpx(r, user_id).id
        out.append(item)
    return {'found': bool(out), 'source': source, 'races': out}

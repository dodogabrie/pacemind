"""Race report service — generates post-race analysis comparing actual vs predicted."""

import logging
from datetime import datetime
from repositories import (
    TrainingPlanRepository, ActivityRepository,
    PredictionRepository, RaceResultRepository,
)
from models.race_result import RaceResult

logger = logging.getLogger(__name__)


class RaceReportService:

    def __init__(self, plan_repo=None, activity_repo=None,
                 prediction_repo=None, result_repo=None):
        self.plan_repo = plan_repo or TrainingPlanRepository()
        self.activity_repo = activity_repo or ActivityRepository()
        self.prediction_repo = prediction_repo or PredictionRepository()
        self.result_repo = result_repo or RaceResultRepository()

    def generate_report(self, plan_id: int, strava_activity_id: int,
                        user_id: int) -> dict:
        """Generate a post-race report comparing actual splits to predicted.

        Returns the saved RaceResult as a dict.
        """
        plan = self.plan_repo.get_user_plan(plan_id, user_id)
        if not plan:
            return {'error': 'Plan not found'}

        activity = self.activity_repo.get_by_id(strava_activity_id)
        if not activity or activity.user_id != user_id:
            return {'error': 'Activity not found'}

        # Check for existing report
        existing = self.result_repo.get_by_plan(plan_id, user_id)
        if existing:
            return existing.to_dict()

        # Get prediction if target GPX exists
        prediction = None
        if plan.target_gpx_id:
            prediction = self.prediction_repo.get_latest_for_gpx(
                plan.target_gpx_id, user_id
            )

        # Build actual splits from streams
        actual_splits = self._build_actual_splits(activity)
        actual_total = sum(s['time_s'] for s in actual_splits) if actual_splits else None

        # Fallback: use activity elapsed time
        if not actual_total:
            actual_total = activity.streams.get('time', [0])[-1] if activity.streams and activity.streams.get('time') else None
            if not actual_total and hasattr(activity, 'elapsed_time'):
                actual_total = activity.elapsed_time

        if not actual_total:
            return {'error': 'Cannot determine actual time from activity streams'}

        # Build predicted splits from prediction segments
        predicted_splits = self._build_predicted_splits(prediction) if prediction else []
        predicted_total = prediction.total_time_seconds if prediction else None

        # Compare splits
        split_comparison = self._compare_splits(actual_splits, predicted_splits)

        # Compute difference
        diff = (actual_total - predicted_total) if predicted_total else None

        # Generate insights
        insights = self._generate_insights(split_comparison)

        # Save result
        result = RaceResult(
            user_id=user_id,
            plan_id=plan_id,
            strava_activity_id=strava_activity_id,
            prediction_id=prediction.id if prediction else None,
            actual_total_seconds=actual_total,
            predicted_total_seconds=predicted_total,
            difference_seconds=diff,
            split_comparison=split_comparison,
            insights=insights,
        )
        self.result_repo.create(result)

        # Mark plan as completed
        plan.status = 'completed'
        self.result_repo.commit()

        return result.to_dict()

    def get_report(self, plan_id: int, user_id: int) -> dict:
        """Get existing race report for a plan."""
        result = self.result_repo.get_by_plan(plan_id, user_id)
        if not result:
            return {'error': 'No race report found for this plan'}
        return result.to_dict()

    def _build_actual_splits(self, activity) -> list:
        """Build per-km splits from activity streams."""
        streams = activity.streams
        if not streams or not isinstance(streams, dict):
            return []

        distance = streams.get('distance', [])
        time_data = streams.get('time', [])
        altitude = streams.get('altitude', [])
        grade = streams.get('grade_smooth', [])

        if not distance or not time_data or len(distance) < 2:
            return []

        splits = []
        km_boundary = 1000.0
        last_time = 0
        last_dist = 0

        for i in range(len(distance)):
            if distance[i] >= km_boundary:
                # Interpolate to exact km boundary
                if i > 0 and distance[i] != distance[i - 1]:
                    frac = (km_boundary - distance[i - 1]) / (distance[i] - distance[i - 1])
                    t_at_km = time_data[i - 1] + frac * (time_data[i] - time_data[i - 1])
                else:
                    t_at_km = time_data[i]

                elapsed = t_at_km - last_time
                km_num = len(splits) + 1

                # Elevation gain for this km
                elev_gain = 0
                avg_grade = 0
                if altitude and len(altitude) > i:
                    # Find points in this km range
                    start_idx = 0
                    for j in range(i):
                        if distance[j] >= (km_boundary - 1000):
                            start_idx = j
                            break
                    for j in range(start_idx + 1, i + 1):
                        if j < len(altitude) and altitude[j] > altitude[j - 1]:
                            elev_gain += altitude[j] - altitude[j - 1]
                    if grade and len(grade) > start_idx:
                        grade_vals = grade[start_idx:i + 1]
                        avg_grade = sum(grade_vals) / len(grade_vals) if grade_vals else 0

                pace = elapsed / 60.0  # min/km
                splits.append({
                    'km': km_num,
                    'time_s': round(elapsed, 1),
                    'pace': round(pace, 2),
                    'elevation_gain': round(elev_gain, 1),
                    'grade': round(avg_grade, 2),
                })

                last_time = t_at_km
                km_boundary += 1000.0

        return splits

    def _build_predicted_splits(self, prediction) -> list:
        """Aggregate prediction 50m segments into 1km buckets."""
        segments = prediction.predicted_segments
        if not segments or not isinstance(segments, list):
            return []

        splits = []
        km_time = 0
        km_distance = 0
        km_grade_sum = 0
        km_elev_gain = 0
        segment_count = 0

        for seg in segments:
            seg_dist = seg.get('distance_m', seg.get('distance', 50))
            seg_time = seg.get('time_s', seg.get('time', 0))
            seg_grade = seg.get('grade', seg.get('grade_mean', 0))
            seg_elev = max(0, seg_grade / 100 * seg_dist) if seg_grade > 0 else 0

            km_time += seg_time
            km_distance += seg_dist
            km_grade_sum += seg_grade
            km_elev_gain += seg_elev
            segment_count += 1

            if km_distance >= 1000:
                km_num = len(splits) + 1
                avg_grade = km_grade_sum / segment_count if segment_count else 0
                pace = km_time / 60.0  # min/km
                splits.append({
                    'km': km_num,
                    'time_s': round(km_time, 1),
                    'pace': round(pace, 2),
                    'elevation_gain': round(km_elev_gain, 1),
                    'grade': round(avg_grade, 2),
                })
                km_time = 0
                km_distance = 0
                km_grade_sum = 0
                km_elev_gain = 0
                segment_count = 0

        # Handle remaining partial km
        if km_distance > 100 and km_time > 0:
            km_num = len(splits) + 1
            avg_grade = km_grade_sum / segment_count if segment_count else 0
            # Scale pace to min/km equivalent
            pace = (km_time / (km_distance / 1000)) / 60.0
            splits.append({
                'km': km_num,
                'time_s': round(km_time, 1),
                'pace': round(pace, 2),
                'elevation_gain': round(km_elev_gain, 1),
                'grade': round(avg_grade, 2),
            })

        return splits

    def _compare_splits(self, actual: list, predicted: list) -> list:
        """Build per-km comparison between actual and predicted."""
        comparison = []
        pred_by_km = {s['km']: s for s in predicted}

        for act in actual:
            km = act['km']
            pred = pred_by_km.get(km)
            entry = {
                'km': km,
                'actual_pace': act['pace'],
                'actual_time_s': act['time_s'],
                'grade': act.get('grade', 0),
                'elevation_gain': act.get('elevation_gain', 0),
            }
            if pred:
                entry['predicted_pace'] = pred['pace']
                entry['predicted_time_s'] = pred['time_s']
                entry['diff_seconds'] = round(act['time_s'] - pred['time_s'], 1)
            else:
                entry['predicted_pace'] = None
                entry['predicted_time_s'] = None
                entry['diff_seconds'] = None
            comparison.append(entry)

        return comparison

    # TODO(i18n-gap #92 — see GH issues): user-facing English built server-side.
    # Italian UI shows it verbatim; return a key + params and render with $t on the client.
    def _generate_insights(self, split_comparison: list) -> list:
        """Generate rule-based insights from split comparison."""
        if not split_comparison:
            return []

        insights = []
        diffs = [(s['km'], s.get('diff_seconds', 0) or 0, s.get('grade', 0))
                 for s in split_comparison]

        # Find consecutive groups where runner was >10s/km slower
        slow_groups = self._find_consecutive_groups(diffs, threshold=10)
        for group in slow_groups:
            start_km, end_km, total_diff, avg_grade = group
            time_str = self._format_diff(total_diff)
            if avg_grade > 5:
                reason = f"steep climb, avg grade {avg_grade:.0f}%"
            elif avg_grade < -5:
                reason = f"steep descent, avg grade {avg_grade:.0f}%"
            elif end_km > len(diffs) * 0.75:
                reason = "late-race fatigue"
            else:
                reason = "pacing"
            if start_km == end_km:
                insights.append(f"Lost {time_str} on km {start_km} ({reason})")
            else:
                insights.append(f"Lost {time_str} on km {start_km}-{end_km} ({reason})")

        # Find consecutive groups where runner was >10s/km faster
        fast_groups = self._find_consecutive_groups(diffs, threshold=-10, slower=False)
        for group in fast_groups:
            start_km, end_km, total_diff, avg_grade = group
            time_str = self._format_diff(abs(total_diff))
            if avg_grade < -3:
                reason = "descent"
            elif avg_grade > 3:
                reason = "strong climbing"
            else:
                reason = "faster than predicted"
            if start_km == end_km:
                insights.append(f"Gained {time_str} on km {start_km} ({reason})")
            else:
                insights.append(f"Gained {time_str} on km {start_km}-{end_km} ({reason})")

        # Overall pace consistency
        if diffs:
            paces = [s.get('actual_pace', 0) for s in split_comparison if s.get('actual_pace')]
            if len(paces) > 2:
                first_half = paces[:len(paces) // 2]
                second_half = paces[len(paces) // 2:]
                avg_first = sum(first_half) / len(first_half)
                avg_second = sum(second_half) / len(second_half)
                fade = ((avg_second - avg_first) / avg_first) * 100
                if fade > 10:
                    insights.append(
                        f"Pace faded {fade:.0f}% in the second half "
                        f"({avg_first:.2f} → {avg_second:.2f} min/km)"
                    )
                elif fade < -5:
                    insights.append(
                        f"Negative split: {abs(fade):.0f}% faster in the second half"
                    )

        return insights

    def _find_consecutive_groups(self, diffs, threshold=10, slower=True):
        """Find consecutive km groups above/below threshold."""
        groups = []
        group_start = None
        group_total = 0
        group_grade_sum = 0
        group_count = 0

        for km, diff, grade in diffs:
            is_match = diff > threshold if slower else diff < threshold
            if is_match:
                if group_start is None:
                    group_start = km
                group_total += diff
                group_grade_sum += grade
                group_count += 1
            else:
                if group_start is not None and group_count >= 1:
                    avg_grade = group_grade_sum / group_count
                    groups.append((group_start, km - 1, group_total, avg_grade))
                group_start = None
                group_total = 0
                group_grade_sum = 0
                group_count = 0

        if group_start is not None and group_count >= 1:
            avg_grade = group_grade_sum / group_count
            groups.append((group_start, diffs[-1][0], group_total, avg_grade))

        return groups

    @staticmethod
    def _format_diff(seconds):
        """Format seconds diff as M:SS."""
        m = int(abs(seconds) // 60)
        s = int(abs(seconds) % 60)
        if m > 0:
            return f"{m}:{s:02d}"
        return f"{s}s"

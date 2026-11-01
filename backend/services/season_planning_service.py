"""Season planning service — multi-race overview and validation."""

import logging
from datetime import datetime, timezone
from repositories import TrainingPlanRepository, PredictionRepository, RaceResultRepository

logger = logging.getLogger(__name__)


class SeasonPlanningService:

    def __init__(self, plan_repo=None, prediction_repo=None, result_repo=None):
        self.plan_repo = plan_repo or TrainingPlanRepository()
        self.prediction_repo = prediction_repo or PredictionRepository()
        self.result_repo = result_repo or RaceResultRepository()

    def get_season_overview(self, user_id: int) -> dict:
        """Get overview of all planned races for the season."""
        plans = self.plan_repo.get_season_plans(user_id)
        today = datetime.now(timezone.utc).date()

        races = []
        for plan in plans:
            # Race countdown
            countdown = None
            if plan.race_date:
                race_date = plan.race_date.date() if isinstance(plan.race_date, datetime) else plan.race_date
                countdown = max(0, (race_date - today).days)

            # Latest prediction
            predicted_time = None
            if plan.target_gpx_id:
                pred = self.prediction_repo.get_latest_for_gpx(plan.target_gpx_id, user_id)
                if pred:
                    predicted_time = pred.total_time_seconds

            # Check for race result
            result = self.result_repo.get_by_plan(plan.id, user_id)

            races.append({
                **plan.to_summary(),
                'race_priority': plan.race_priority,
                'countdown': countdown,
                'predicted_time': predicted_time,
                'has_result': result is not None,
            })

        # Validate sequencing
        warnings = self.validate_season_sequencing(plans)

        return {
            'races': races,
            'warnings': warnings,
            'total_races': len(races),
        }

    # TODO(coach-review #9 — see GH issues): we validate, we don't propose.
    # When the user creates a 100K/100M A-race, we should query race_calendar with
    # the right date windows ([R-8w, R-6w] for ~0.5D, [R-4w, R-3w] for ~0.2D),
    # rank by _score_race, and surface tune-up candidates. Add
    # tuneup_recommendation_service alongside this validator.
    def validate_season_sequencing(self, plans) -> list:
        """Validate season race sequencing and return warnings."""
        warnings = []
        dated_plans = [p for p in plans if p.race_date]
        dated_plans.sort(key=lambda p: p.race_date)

        for i in range(1, len(dated_plans)):
            prev = dated_plans[i - 1]
            curr = dated_plans[i]
            prev_date = prev.race_date.date() if isinstance(prev.race_date, datetime) else prev.race_date
            curr_date = curr.race_date.date() if isinstance(curr.race_date, datetime) else curr.race_date
            gap_days = (curr_date - prev_date).days

            if gap_days < 14:
                warnings.append(
                    f"Only {gap_days} days between '{prev.plan_name}' and "
                    f"'{curr.plan_name}'. Consider at least 2 weeks recovery."
                )

            # Warning if B-race before A-race without enough recovery
            if prev.race_priority == 'B' and curr.race_priority == 'A' and gap_days < 21:
                warnings.append(
                    f"B-race '{prev.plan_name}' is only {gap_days} days before "
                    f"A-race '{curr.plan_name}'. Allow 3+ weeks for recovery and taper."
                )

        # Check A-race has taper
        a_races = [p for p in dated_plans if p.race_priority == 'A']
        for a_race in a_races:
            if a_race.weeks:
                last_week = a_race.weeks[-1] if a_race.weeks else {}
                theme = (last_week.get('theme') or '').lower()
                if 'taper' not in theme:
                    warnings.append(
                        f"A-race '{a_race.plan_name}' plan doesn't end with a taper week."
                    )

        return warnings

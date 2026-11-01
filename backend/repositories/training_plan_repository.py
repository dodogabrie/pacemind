"""Training plan and workout completion repository."""

from typing import Optional, List
from models import TrainingPlan, WorkoutCompletion
from database import db
from repositories.base import BaseRepository


class TrainingPlanRepository(BaseRepository[TrainingPlan]):
    model = TrainingPlan

    def get_user_plans(self, user_id: int) -> List[TrainingPlan]:
        """Get all plans for user, newest first."""
        return TrainingPlan.query.filter_by(user_id=user_id) \
            .order_by(TrainingPlan.created_at.desc()).all()

    def get_active_plans(self, user_id: int) -> List[TrainingPlan]:
        """Get active plans for user."""
        return TrainingPlan.query.filter_by(
            user_id=user_id, status='active'
        ).all()

    def get_season_plans(self, user_id: int) -> List[TrainingPlan]:
        """Get all non-completed plans ordered by race_date ASC."""
        return TrainingPlan.query.filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.status != 'completed'
        ).order_by(TrainingPlan.race_date.asc().nullslast()).all()

    def get_user_plan(self, plan_id: int, user_id: int) -> Optional[TrainingPlan]:
        return self.find_one_by(id=plan_id, user_id=user_id)

    def get_completion(self, plan_id: int, week_number: int, day: str) -> Optional[WorkoutCompletion]:
        """Get a specific workout completion."""
        return WorkoutCompletion.query.filter_by(
            plan_id=plan_id, week_number=week_number, day=day
        ).first()

    def get_completions_for_plan(self, plan_id: int) -> List[WorkoutCompletion]:
        """Get all workout completions for a plan."""
        return WorkoutCompletion.query.filter_by(plan_id=plan_id).all()

    def create_completion(self, **kwargs) -> WorkoutCompletion:
        """Create a workout completion record."""
        completion = WorkoutCompletion(**kwargs)
        db.session.add(completion)
        db.session.flush()
        return completion

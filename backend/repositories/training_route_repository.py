"""Training route repository."""

from typing import Optional, List
from models.training_route import TrainingRoute
from repositories.base import BaseRepository


class TrainingRouteRepository(BaseRepository[TrainingRoute]):
    model = TrainingRoute

    def get_user_routes(self, user_id: int) -> List[TrainingRoute]:
        """Get all routes for user, newest first."""
        return TrainingRoute.query.filter_by(user_id=user_id) \
            .order_by(TrainingRoute.created_at.desc()).all()

    def get_user_route(self, route_id: int, user_id: int) -> Optional[TrainingRoute]:
        return self.find_one_by(id=route_id, user_id=user_id)

    def search_by_location(
        self, user_id: int, lat: float, lon: float, radius_km: float = 30
    ) -> List[TrainingRoute]:
        """Search routes near a location (rough bounding box filter)."""
        # ~0.009 degrees per km latitude, longitude varies with lat
        import math
        lat_delta = radius_km * 0.009
        lon_delta = radius_km * 0.009 / max(math.cos(math.radians(lat)), 0.1)

        return TrainingRoute.query.filter(
            TrainingRoute.user_id == user_id,
            TrainingRoute.center_lat.between(lat - lat_delta, lat + lat_delta),
            TrainingRoute.center_lon.between(lon - lon_delta, lon + lon_delta),
        ).order_by(TrainingRoute.created_at.desc()).all()

    def search_by_criteria(
        self, user_id: int,
        min_distance_km: Optional[float] = None,
        max_distance_km: Optional[float] = None,
        min_elevation_m: Optional[float] = None,
        max_elevation_m: Optional[float] = None,
    ) -> List[TrainingRoute]:
        """Search routes matching distance/elevation criteria."""
        q = TrainingRoute.query.filter_by(user_id=user_id)

        if min_distance_km is not None:
            q = q.filter(TrainingRoute.distance_km >= min_distance_km)
        if max_distance_km is not None:
            q = q.filter(TrainingRoute.distance_km <= max_distance_km)
        if min_elevation_m is not None:
            q = q.filter(TrainingRoute.elevation_gain_m >= min_elevation_m)
        if max_elevation_m is not None:
            q = q.filter(TrainingRoute.elevation_gain_m <= max_elevation_m)

        return q.order_by(TrainingRoute.created_at.desc()).all()

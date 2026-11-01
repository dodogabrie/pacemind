"""Race repository — query the public race calendar."""

from __future__ import annotations

import math
from datetime import date
from typing import List, Optional

from models.race import Race
from repositories.base import BaseRepository


class RaceRepository(BaseRepository[Race]):
    model = Race

    def get_by_slug(self, slug: str) -> Optional[Race]:
        return self.find_one_by(slug=slug)

    def find_by_source_external(
        self, source: str, external_id: str
    ) -> Optional[Race]:
        return self.find_one_by(source=source, external_id=external_id)

    def search(
        self,
        *,
        q: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        country: Optional[str] = None,
        min_distance_km: Optional[float] = None,
        max_distance_km: Optional[float] = None,
        min_elev_m: Optional[float] = None,
        max_elev_m: Optional[float] = None,
        surface: Optional[str] = None,
        race_type: Optional[str] = None,
        near_lat: Optional[float] = None,
        near_lon: Optional[float] = None,
        max_travel_km: Optional[float] = None,
        sort: str = 'date',
        limit: int = 50,
        offset: int = 0,
    ) -> List[Race]:
        """Filter + sort + paginate races.

        ``near_lat``/``near_lon``/``max_travel_km`` apply a bounding-box
        prefilter in SQL (cheap). The caller is expected to compute precise
        haversine distance + ``fit_score`` if needed — this repo stays
        domain-light.
        """
        query = Race.query

        if q:
            like = f"%{q.lower()}%"
            query = query.filter(
                (Race.name.ilike(like))
                | (Race.location.ilike(like))
                | (Race.region.ilike(like))
            )
        if start_date is not None:
            query = query.filter(Race.date >= start_date)
        if end_date is not None:
            query = query.filter(Race.date <= end_date)
        if country:
            query = query.filter(Race.country == country.upper())
        if min_distance_km is not None:
            query = query.filter(Race.distance_km >= min_distance_km)
        if max_distance_km is not None:
            query = query.filter(Race.distance_km <= max_distance_km)
        if min_elev_m is not None:
            query = query.filter(Race.elev_gain_m >= min_elev_m)
        if max_elev_m is not None:
            query = query.filter(Race.elev_gain_m <= max_elev_m)
        if surface:
            query = query.filter(Race.surface == surface)
        if race_type:
            query = query.filter(Race.race_type == race_type)

        if (
            near_lat is not None
            and near_lon is not None
            and max_travel_km is not None
            and max_travel_km > 0
        ):
            lat_delta = max_travel_km / 111.0
            cos_lat = max(math.cos(math.radians(near_lat)), 0.1)
            lon_delta = max_travel_km / (111.0 * cos_lat)
            query = query.filter(
                Race.lat.between(near_lat - lat_delta, near_lat + lat_delta),
                Race.lon.between(near_lon - lon_delta, near_lon + lon_delta),
            )

        if sort == 'distance':
            query = query.order_by(Race.distance_km.asc(), Race.date.asc())
        else:
            query = query.order_by(Race.date.asc(), Race.distance_km.asc())

        if offset:
            query = query.offset(offset)
        return query.limit(min(max(limit, 1), 100)).all()

    def count_for_filters(self, **kwargs) -> int:
        """Total count for the same filter set (without limit/offset)."""
        kwargs.pop('limit', None)
        kwargs.pop('offset', None)
        kwargs.pop('sort', None)
        results = self.search(limit=10_000, offset=0, **kwargs)
        return len(results)

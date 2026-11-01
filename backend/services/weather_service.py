"""Weather enrichment service using Open-Meteo API.

Provides historical weather data for past activity calibration and
forecast data for future predictions. Completely free, no API key needed.

Weather factors affect running performance through:
- Heat stress (cardiac drift, dehydration)
- Humidity (impaired evaporative cooling)
- Wind (increased aerodynamic resistance)
- Precipitation (wet trail surfaces, visibility)
"""

import requests
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from repositories import WeatherCacheRepository

logger = logging.getLogger(__name__)

# Open-Meteo API endpoints (free, no key required)
HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Weather variables to fetch
WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
    "apparent_temperature",
]

# Cache TTL
HISTORICAL_CACHE_TTL_DAYS = 365  # Historical data doesn't change
FORECAST_CACHE_TTL_HOURS = 6     # Forecasts update frequently


from models.weather_cache import WeatherCache


class WeatherService:
    """Fetch and process weather data for trail running predictions."""

    def __init__(self, weather_cache_repo=None):
        self.weather_cache_repo = weather_cache_repo or WeatherCacheRepository()

    def get_historical_weather(
        self,
        latitude: float,
        longitude: float,
        date: datetime
    ) -> Optional[Dict]:
        """Get historical weather for a past activity.

        Args:
            latitude: Route center latitude
            longitude: Route center longitude
            date: Activity date

        Returns:
            Weather dict with temperature_c, humidity_pct, wind_speed_ms,
            precipitation_mm, apparent_temperature_c, weather_factor
        """
        date_str = date.strftime("%Y-%m-%d")
        cache_key = self._cache_key("hist", latitude, longitude, date_str)

        # Check cache
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            params = {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "start_date": date_str,
                "end_date": date_str,
                "hourly": ",".join(WEATHER_VARIABLES),
                "timezone": "auto",
            }

            response = requests.get(HISTORICAL_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            weather = self._extract_hourly_average(data, date)
            if weather:
                weather['weather_factor'] = self.compute_weather_factor(
                    weather['temperature_c'],
                    weather['humidity_pct'],
                    weather['wind_speed_ms']
                )
                self._set_cached(cache_key, weather, "historical")

            return weather

        except Exception as e:
            logger.warning(f"Failed to fetch historical weather: {e}")
            return None

    def get_forecast_weather(
        self,
        latitude: float,
        longitude: float,
        date: Optional[datetime] = None
    ) -> Optional[Dict]:
        """Get forecast weather for a future prediction.

        Args:
            latitude: Route center latitude
            longitude: Route center longitude
            date: Target date (default: today). Max 16 days ahead.

        Returns:
            Weather dict with forecast conditions and weather_factor
        """
        if date is None:
            date = datetime.now(timezone.utc)

        date_str = date.strftime("%Y-%m-%d")
        cache_key = self._cache_key("fcst", latitude, longitude, date_str)

        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            params = {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "start_date": date_str,
                "end_date": date_str,
                "hourly": ",".join(WEATHER_VARIABLES),
                "timezone": "auto",
            }

            response = requests.get(FORECAST_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            weather = self._extract_hourly_average(data, date)
            if weather:
                weather['weather_factor'] = self.compute_weather_factor(
                    weather['temperature_c'],
                    weather['humidity_pct'],
                    weather['wind_speed_ms']
                )
                weather['is_forecast'] = True
                self._set_cached(cache_key, weather, "forecast")

            return weather

        except Exception as e:
            logger.warning(f"Failed to fetch forecast weather: {e}")
            return None

    def get_weather_for_route(
        self,
        points: List[Dict],
        date: Optional[datetime] = None,
        is_historical: bool = False
    ) -> Optional[Dict]:
        """Get weather for a route using its center point.

        Args:
            points: Route points with 'lat' and 'lon' keys
            date: Activity/prediction date
            is_historical: Whether this is for a past activity

        Returns:
            Weather dict
        """
        if not points:
            return None

        # Use route centroid
        lats = [p['lat'] for p in points if 'lat' in p]
        lons = [p['lon'] for p in points if 'lon' in p]

        if not lats or not lons:
            return None

        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

        if is_historical and date:
            return self.get_historical_weather(center_lat, center_lon, date)
        else:
            return self.get_forecast_weather(center_lat, center_lon, date)

    @staticmethod
    def compute_weather_factor(
        temperature_c: float,
        humidity_pct: float,
        wind_speed_ms: float = 0.0
    ) -> float:
        """Compute performance degradation factor from weather conditions.

        Based on sports science research on thermoregulation:
        - Above 15°C, each degree costs ~0.3% performance (cardiac drift)
        - Above 50% humidity, each % costs ~0.5% (impaired cooling)
        - Headwind adds resistance (simplified as uniform penalty)

        Conservative model — real effects can be larger in extreme conditions.

        Args:
            temperature_c: Temperature in Celsius
            humidity_pct: Relative humidity percentage
            wind_speed_ms: Wind speed in m/s

        Returns:
            Slowdown factor >= 1.0 (1.0 = ideal conditions)
        """
        # Heat stress: gradual effect above 15°C, accelerating above 25°C
        heat_penalty = 0.0
        if temperature_c > 15.0:
            base_heat = (temperature_c - 15.0) * 0.003
            # Accelerating effect above 25°C
            if temperature_c > 25.0:
                base_heat += (temperature_c - 25.0) * 0.004
            heat_penalty = base_heat

        # Humidity stress: impairs evaporative cooling above 50%
        humidity_penalty = 0.0
        if humidity_pct > 50.0:
            humidity_penalty = (humidity_pct - 50.0) * 0.0005

        # Combined heat+humidity interaction (multiplicative stress)
        if temperature_c > 20.0 and humidity_pct > 60.0:
            humidity_penalty *= 1.0 + (temperature_c - 20.0) * 0.02

        # Wind penalty (simplified — doesn't account for direction)
        wind_penalty = wind_speed_ms * 0.002 if wind_speed_ms > 5.0 else 0.0

        # Cold penalty (below 0°C, stiff muscles, respiratory stress)
        cold_penalty = 0.0
        if temperature_c < 0.0:
            cold_penalty = abs(temperature_c) * 0.002

        factor = 1.0 + heat_penalty + humidity_penalty + wind_penalty + cold_penalty

        # Cap at reasonable maximum (30% slowdown)
        return min(factor, 1.30)

    def _extract_hourly_average(self, api_data: Dict, date: datetime) -> Optional[Dict]:
        """Extract average conditions from hourly data.

        Averages over typical running hours (6am-6pm) for the given date.

        Args:
            api_data: Raw Open-Meteo API response
            date: Target date

        Returns:
            Averaged weather dict
        """
        hourly = api_data.get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            return None

        # Get indices for daytime hours (6am to 6pm)
        target_date = date.strftime("%Y-%m-%d")
        daytime_indices = []
        for i, t in enumerate(times):
            if t.startswith(target_date):
                hour = int(t.split("T")[1].split(":")[0])
                if 6 <= hour <= 18:
                    daytime_indices.append(i)

        if not daytime_indices:
            # Fallback: use all hours for the date
            daytime_indices = [i for i, t in enumerate(times) if t.startswith(target_date)]

        if not daytime_indices:
            return None

        def safe_avg(key):
            values = [hourly[key][i] for i in daytime_indices if i < len(hourly.get(key, []))]
            values = [v for v in values if v is not None]
            return sum(values) / len(values) if values else 0.0

        return {
            'temperature_c': round(safe_avg("temperature_2m"), 1),
            'humidity_pct': round(safe_avg("relative_humidity_2m"), 1),
            'wind_speed_ms': round(safe_avg("wind_speed_10m") / 3.6, 1),  # km/h -> m/s
            'precipitation_mm': round(safe_avg("precipitation"), 1),
            'apparent_temperature_c': round(safe_avg("apparent_temperature"), 1),
            'date': target_date,
        }

    def _cache_key(self, prefix: str, lat: float, lon: float, date_str: str) -> str:
        """Generate cache key."""
        raw = f"{prefix}:{lat:.4f}:{lon:.4f}:{date_str}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get from cache if not expired."""
        return self.weather_cache_repo.get_cached(key)

    def _set_cached(self, key: str, data: Dict, cache_type: str):
        """Store in cache."""
        if cache_type == "historical":
            expires = datetime.now(timezone.utc) + timedelta(days=HISTORICAL_CACHE_TTL_DAYS)
        else:
            expires = datetime.now(timezone.utc) + timedelta(hours=FORECAST_CACHE_TTL_HOURS)

        try:
            self.weather_cache_repo.set_cached(key, data, cache_type, expires)
            self.weather_cache_repo.commit()
        except Exception:
            self.weather_cache_repo.rollback()

    def describe_conditions(self, weather: Dict) -> str:
        """Generate a human-readable weather summary for the agent.

        Args:
            weather: Weather dict from get_historical/forecast_weather

        Returns:
            Description string like "Warm (28°C), humid (72%), light wind"
        """
        temp = weather.get('temperature_c', 0)
        humidity = weather.get('humidity_pct', 0)
        wind = weather.get('wind_speed_ms', 0)
        precip = weather.get('precipitation_mm', 0)
        factor = weather.get('weather_factor', 1.0)

        # Temperature description
        if temp < 0:
            temp_desc = f"Freezing ({temp}°C)"
        elif temp < 10:
            temp_desc = f"Cold ({temp}°C)"
        elif temp < 18:
            temp_desc = f"Cool ({temp}°C)"
        elif temp < 25:
            temp_desc = f"Warm ({temp}°C)"
        elif temp < 32:
            temp_desc = f"Hot ({temp}°C)"
        else:
            temp_desc = f"Extreme heat ({temp}°C)"

        # Humidity
        if humidity > 80:
            hum_desc = f"very humid ({humidity}%)"
        elif humidity > 60:
            hum_desc = f"humid ({humidity}%)"
        elif humidity > 40:
            hum_desc = f"moderate humidity ({humidity}%)"
        else:
            hum_desc = f"dry ({humidity}%)"

        # Wind
        if wind > 10:
            wind_desc = f"strong wind ({wind:.0f} m/s)"
        elif wind > 5:
            wind_desc = f"moderate wind ({wind:.0f} m/s)"
        elif wind > 2:
            wind_desc = "light wind"
        else:
            wind_desc = "calm"

        # Rain
        rain_desc = f", {precip:.1f}mm rain" if precip > 0.5 else ""

        # Impact
        impact_pct = (factor - 1.0) * 100
        if impact_pct > 10:
            impact = f"Significant performance impact (~{impact_pct:.0f}% slower)"
        elif impact_pct > 5:
            impact = f"Moderate performance impact (~{impact_pct:.0f}% slower)"
        elif impact_pct > 2:
            impact = f"Minor performance impact (~{impact_pct:.0f}% slower)"
        else:
            impact = "Minimal performance impact"

        return f"{temp_desc}, {hum_desc}, {wind_desc}{rain_desc}. {impact}."

    def get_forecast_with_sun(
        self,
        latitude: float,
        longitude: float,
        date: Optional[datetime] = None
    ) -> Optional[Dict]:
        """Get forecast weather including sunrise/sunset and weathercode.

        Args:
            latitude: Route center latitude
            longitude: Route center longitude
            date: Target date (default: today). Max 16 days ahead.

        Returns:
            Weather dict with forecast conditions, sunrise, sunset, daylight_hours
        """
        if date is None:
            date = datetime.now(timezone.utc)

        date_str = date.strftime("%Y-%m-%d")
        cache_key = self._cache_key("fsun", latitude, longitude, date_str)

        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            params = {
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "start_date": date_str,
                "end_date": date_str,
                "hourly": ",".join(WEATHER_VARIABLES),
                "daily": "sunrise,sunset,weathercode",
                "timezone": "auto",
            }

            response = requests.get(FORECAST_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            weather = self._extract_hourly_average(data, date)
            if not weather:
                return None

            weather['weather_factor'] = self.compute_weather_factor(
                weather['temperature_c'],
                weather['humidity_pct'],
                weather['wind_speed_ms']
            )
            weather['is_forecast'] = True

            # Extract sunrise/sunset from daily data
            daily = data.get("daily", {})
            sunrise_list = daily.get("sunrise", [])
            sunset_list = daily.get("sunset", [])
            weathercode_list = daily.get("weathercode", [])

            if sunrise_list and sunset_list:
                # Format: "2026-03-07T06:45" -> "06:45"
                sunrise_raw = sunrise_list[0]
                sunset_raw = sunset_list[0]
                weather['sunrise'] = sunrise_raw.split("T")[1] if "T" in sunrise_raw else sunrise_raw
                weather['sunset'] = sunset_raw.split("T")[1] if "T" in sunset_raw else sunset_raw

                # Compute daylight hours
                try:
                    sr = datetime.strptime(sunrise_raw, "%Y-%m-%dT%H:%M")
                    ss = datetime.strptime(sunset_raw, "%Y-%m-%dT%H:%M")
                    weather['daylight_hours'] = round((ss - sr).total_seconds() / 3600, 2)
                except ValueError:
                    weather['daylight_hours'] = None
            else:
                weather['sunrise'] = None
                weather['sunset'] = None
                weather['daylight_hours'] = None

            if weathercode_list:
                weather['weathercode'] = weathercode_list[0]
            else:
                weather['weathercode'] = None

            self._set_cached(cache_key, weather, "forecast")
            return weather

        except Exception as e:
            logger.warning(f"Failed to fetch forecast with sun data: {e}")
            return None

    def get_recent_weather_summary(
        self,
        latitude: float,
        longitude: float,
        target_date: Optional[datetime] = None,
        days: int = 5
    ) -> Optional[Dict]:
        """Get weather summary for the days leading up to target_date.

        Fetches precipitation data for the days before the target date to
        assess trail/terrain conditions. Uses historical API for past days
        and forecast API for future days.

        Args:
            latitude: Route center latitude
            longitude: Route center longitude
            target_date: The planned run date (default: today)
            days: Number of days before target to summarize (default 5)

        Returns:
            Dict with per-day breakdown, total precipitation, and terrain impact
        """
        today = datetime.now(timezone.utc).date()
        if target_date is None:
            target = today
        else:
            target = target_date.date() if isinstance(target_date, datetime) else target_date

        end_date = target - timedelta(days=1)
        start_date = target - timedelta(days=days)

        cache_key = self._cache_key(
            "recent", latitude, longitude,
            f"{start_date.isoformat()}_{end_date.isoformat()}"
        )
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            day_list = []
            total_precip = 0.0

            # Split into historical (past) and forecast (future) ranges
            yesterday = today - timedelta(days=1)
            hist_start = start_date
            hist_end = min(end_date, yesterday)
            fcst_start = max(start_date, today)
            fcst_end = end_date

            # Fetch historical days (up to yesterday)
            if hist_start <= yesterday:
                hist_data = self._fetch_daily_precip(
                    latitude, longitude, hist_start, hist_end, use_forecast=False
                )
                day_list.extend(hist_data)

            # Fetch forecast days (today onwards)
            if fcst_start <= fcst_end:
                fcst_data = self._fetch_daily_precip(
                    latitude, longitude, fcst_start, fcst_end, use_forecast=True
                )
                # Mark forecast days
                for d in fcst_data:
                    d['is_forecast'] = True
                day_list.extend(fcst_data)

            total_precip = round(sum(d['precipitation_mm'] for d in day_list), 1)

            # Assess terrain impact based on accumulated precipitation
            if total_precip < 2:
                terrain_impact = "Dry conditions - trails should be in good shape"
            elif total_precip < 10:
                terrain_impact = "Some moisture - trails may be damp in shaded areas"
            elif total_precip < 25:
                terrain_impact = "Significant recent rain - expect mud and wet rocks"
            else:
                terrain_impact = "Heavy recent precipitation - trails will be muddy, streams may be high"

            # Note if assessment includes forecast data
            has_forecast = any(d.get('is_forecast') for d in day_list)
            if has_forecast:
                terrain_impact += " (includes forecast)"

            result = {
                'days': day_list,
                'total_precipitation_mm': total_precip,
                'terrain_impact': terrain_impact,
                'target_date': target.isoformat(),
                'includes_forecast': has_forecast,
            }

            self._set_cached(cache_key, result, "forecast")  # 6h TTL
            return result

        except Exception as e:
            logger.warning(f"Failed to fetch weather summary: {e}")
            return None

    def _fetch_daily_precip(
        self,
        latitude: float,
        longitude: float,
        start_date,
        end_date,
        use_forecast: bool = False
    ) -> List[Dict]:
        """Fetch daily precipitation from Open-Meteo (historical or forecast).

        Args:
            latitude, longitude: Location
            start_date, end_date: Date range (date objects)
            use_forecast: If True, use forecast API; else historical archive

        Returns:
            List of dicts with date, precipitation_mm, temperature_c
        """
        url = FORECAST_URL if use_forecast else HISTORICAL_URL
        params = {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "precipitation_sum,temperature_2m_mean",
            "timezone": "auto",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        precip_values = daily.get("precipitation_sum", [])
        temp_values = daily.get("temperature_2m_mean", [])

        result = []
        for i, d in enumerate(dates):
            precip = precip_values[i] if i < len(precip_values) and precip_values[i] is not None else 0.0
            temp = temp_values[i] if i < len(temp_values) and temp_values[i] is not None else None
            result.append({
                'date': d,
                'precipitation_mm': round(precip, 1),
                'temperature_c': round(temp, 1) if temp is not None else None,
            })

        return result

    @staticmethod
    def get_forecast_accuracy(target_date: datetime) -> Dict:
        """Classify forecast accuracy based on how far ahead the target date is.

        Open-Meteo forecast reliability:
        - 1-3 days: High accuracy, hourly data very reliable
        - 4-7 days: Moderate, general trends reliable but details may shift
        - 8-16 days: Low, expect significant changes

        Args:
            target_date: The date being forecast

        Returns:
            Dict with level, label, and description
        """
        today = datetime.now(timezone.utc).date()
        target = target_date.date() if isinstance(target_date, datetime) else target_date
        days_ahead = (target - today).days

        if days_ahead <= 3:
            return {
                'level': 'high',
                'label': 'High accuracy',
                'description': '1-3 day forecast, very reliable',
                'days_ahead': days_ahead,
            }
        elif days_ahead <= 7:
            return {
                'level': 'moderate',
                'label': 'Moderate accuracy',
                'description': '4-7 day forecast, general trends reliable',
                'days_ahead': days_ahead,
            }
        else:
            return {
                'level': 'low',
                'label': 'Low accuracy',
                'description': '8-16 day forecast, conditions may change significantly',
                'days_ahead': days_ahead,
            }

    def get_weather_widget_data(
        self,
        latitude: float,
        longitude: float,
        date: datetime
    ) -> Optional[Dict]:
        """Get all weather data needed by the frontend widget.

        Combines forecast (with sunrise/sunset), accuracy classification,
        recent weather summary, and human-readable description.

        Args:
            latitude: Route center latitude
            longitude: Route center longitude
            date: Target date for forecast

        Returns:
            Combined dict with forecast, accuracy, recent_weather, conditions_description
        """
        forecast = self.get_forecast_with_sun(latitude, longitude, date)
        if not forecast:
            return None

        accuracy = self.get_forecast_accuracy(date)
        recent_weather = self.get_recent_weather_summary(latitude, longitude, target_date=date)
        conditions_description = self.describe_conditions(forecast)

        return {
            'forecast': forecast,
            'accuracy': accuracy,
            'recent_weather': recent_weather,
            'conditions_description': conditions_description,
        }

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from .physics_model.calibration import calibrate_user_params, DEFAULT_PARAMS
from .physics_model.pipeline import (
    run_physics_prediction,
    DEFAULT_FATIGUE_ALPHA,
    DEFAULT_ULTRA_BETA,
    DEFAULT_ULTRA_GAMMA
)

logger = logging.getLogger(__name__)


class PhysicsPredictionService:
    def __init__(self):
        pass

    def prepare_streams_for_calibration(self, raw_activities_streams: List[Dict]) -> List[pd.DataFrame]:
        """
        Convert raw Strava stream dicts into DataFrames expected by calibration.
        """
        dfs = []
        for s in raw_activities_streams:
            try:
                # Basic validation
                if 'distance' not in s or 'velocity_smooth' not in s or 'grade_smooth' not in s:
                    continue

                # Create DF
                df = pd.DataFrame({
                    'distance': s['distance'],
                    'velocity_smooth': s['velocity_smooth'],
                    'grade_smooth': s['grade_smooth'],
                    'moving': s.get('moving', [True]*len(s['distance']))
                })
                dfs.append(df)
            except Exception as e:
                logger.warning("Error preparing stream: %s", e)
                continue
        return dfs

    def calibrate(self, activity_streams: List[Dict]) -> Dict[str, float]:
        """
        Calibrate user parameters from a list of activity streams.
        """
        if not activity_streams:
            return DEFAULT_PARAMS

        dfs = self.prepare_streams_for_calibration(activity_streams)
        if not dfs:
            return DEFAULT_PARAMS

        return calibrate_user_params(dfs)

    def predict(
        self,
        gpx_points: List[Dict],
        user_params: Dict[str, float],
        user_id: Optional[int] = None,
        ultra_beta: float = DEFAULT_ULTRA_BETA,
        ultra_gamma: float = DEFAULT_ULTRA_GAMMA
    ) -> Dict:
        """
        Predict time for a GPX route.

        Uses a two-phase fatigue model:
        - Phase 1: Base eccentric fatigue (linear, unchanged for <42km)
        - Phase 2: Ultra-distance multiplier (exponential, activates >42km)

        Args:
            gpx_points: List of dicts {'distance', 'elevation'} (cumulative distance)
            user_params: Physics parameters
            user_id: Unused; kept for call-site compatibility
            ultra_beta: Ultra fatigue intensity coefficient (default 0.4)
            ultra_gamma: Non-linearity exponent for ultra fatigue (default 1.5)

        Returns:
            Prediction result dict
        """
        if not gpx_points:
            return {'error': 'No GPX points'}

        # Convert to DataFrame
        df = pd.DataFrame(gpx_points)

        # Resample to 50m intervals (SAME AS ML MODEL) for consistent elevation
        try:
            max_dist = df['distance'].max()
            new_dist = np.arange(0, max_dist, 50.0)

            new_elev = np.interp(new_dist, df['distance'], df['elevation'])

            resampled_df = pd.DataFrame({
                'distance': new_dist,
                'elevation': new_elev
            })

            # ponytail: ultra term always uses the defaults; the per-user ultra
            # fit ignored D+ and saw future activities (pred-review, F5).
            fatigue_alpha = user_params.get('fatigue_alpha', DEFAULT_FATIGUE_ALPHA)

            result = run_physics_prediction(
                resampled_df,
                user_params,
                fatigue_alpha=fatigue_alpha,
                ultra_beta=ultra_beta,
                ultra_gamma=ultra_gamma
            )

            # Log fatigue diagnostics
            if 'diagnostics' in result:
                diag = result['diagnostics']
                logger.info(
                    "Fatigue diagnostics: alpha=%.3f, route=%.1fkm, "
                    "final_fatigue=%.3f (base=%.3f, ultra=%.3f), avg_slowdown=%.2f%%",
                    diag.get('fatigue_alpha', 0),
                    diag.get('total_distance_km', 0),
                    diag.get('final_fatigue_factor', 1.0),
                    diag.get('final_base_fatigue', 1.0),
                    diag.get('final_ultra_multiplier', 1.0),
                    diag.get('avg_fatigue_slowdown_pct', 0)
                )

            # Add resampled elevation profile for accurate elevation gain calculation
            result['resampled_elevations'] = new_elev.tolist()
            result['resampled_distances'] = new_dist.tolist()
            result['user_params'] = user_params
            result['fatigue_alpha'] = fatigue_alpha
            result['ultra_beta'] = ultra_beta
            result['ultra_gamma'] = ultra_gamma

            return result

        except Exception as e:
            logger.exception("Prediction error: %s", e)
            return {'error': str(e)}

"""Auto-prediction service for MVP flow.

Handles automatic activity download and prediction after GPX upload.
"""
import threading
from typing import Dict, List
from datetime import datetime, timedelta
from flask import current_app
from models.prediction import Prediction
from repositories import GPXFileRepository, PredictionRepository
from services.hybrid_prediction_service import HybridPredictionService
import logging

logger = logging.getLogger(__name__)


class AutoPredictionService:
    """Handles automatic activity download and prediction for uploaded GPX files."""

    def __init__(self, gpx_repo=None, prediction_repo=None):
        self.prediction_service = HybridPredictionService()
        self.gpx_repo = gpx_repo or GPXFileRepository()
        self.prediction_repo = prediction_repo or PredictionRepository()

    def process_gpx_async(self, gpx_id: int, user_id: int):
        """Process GPX file asynchronously: download activities and predict.

        Args:
            gpx_id: ID of uploaded GPX file
            user_id: ID of user who uploaded the GPX
        """
        thread = threading.Thread(
            target=self._process_gpx_background,
            args=(gpx_id, user_id)
        )
        thread.daemon = True
        thread.start()

    def _process_gpx_background(self, gpx_id: int, user_id: int):
        """Background worker to download activities and predict.

        Args:
            gpx_id: ID of uploaded GPX file
            user_id: ID of user
        """
        try:
            # Create new app context for background thread
            from app import create_app
            app = create_app()

            with app.app_context():
                # Create fresh repos inside app context for background thread
                gpx_repo = GPXFileRepository()
                prediction_repo = PredictionRepository()

                # Update status to processing
                gpx_file = gpx_repo.get_by_id(gpx_id)
                if not gpx_file:
                    logger.error(f"GPX file {gpx_id} not found")
                    return

                # Update status to predicting (no download, model already trained at login)
                gpx_file.processing_status = 'predicting'
                gpx_repo.commit()

                # Run prediction
                gpx_data = gpx_file.data
                if not gpx_data or 'points' not in gpx_data:
                    gpx_file.processing_status = 'error'
                    gpx_file.error_message = 'Invalid GPX data'
                    gpx_repo.commit()
                    return

                prediction_result = self.prediction_service.predict(
                    user_id=user_id,
                    gpx_points=gpx_data['points'],
                    effort='race'  # uploaded GPX = a race to plan
                )

                # Save prediction to database (NEW format)
                # Extract tier from metadata
                tier_str = prediction_result.get('metadata', {}).get('tier', 'TIER_1_PHYSICS')
                tier_num = int(tier_str.split('_')[1]) if 'TIER_' in tier_str else 1

                prediction = Prediction(
                    user_id=user_id,
                    gpx_file_id=gpx_id,
                    tier=tier_num,
                    effort_level='race',
                    prediction_data=prediction_result
                )
                prediction_repo.create(prediction)  # flush to get ID

                # Update GPX status to completed
                gpx_file.processing_status = 'completed'
                gpx_file.prediction_id = prediction.id
                prediction_repo.commit()

                logger.info(f"Auto-prediction completed for GPX {gpx_id}, prediction ID {prediction.id}")

        except Exception as e:
            logger.error(f"Error in auto-prediction for GPX {gpx_id}: {str(e)}", exc_info=True)
            try:
                from app import create_app
                app = create_app()
                with app.app_context():
                    err_gpx_repo = GPXFileRepository()
                    gpx_file = err_gpx_repo.get_by_id(gpx_id)
                    if gpx_file:
                        gpx_file.processing_status = 'error'
                        gpx_file.error_message = str(e)
                        err_gpx_repo.commit()
            except Exception as inner_e:
                logger.error(f"Failed to update error status: {str(inner_e)}")

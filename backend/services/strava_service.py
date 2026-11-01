import logging
import requests
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Default timeout for all Strava HTTP calls (seconds).
STRAVA_HTTP_TIMEOUT = 30


class StravaNotConnected(Exception):
    """The user never connected Strava (signed up by email, imports files)."""


class StravaService:
    """Service for interacting with Strava API."""

    BASE_URL = 'https://www.strava.com'
    API_URL = 'https://www.strava.com/api/v3'

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_auth_url(self, state=None):
        """Generate Strava authorization URL."""
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'approval_prompt': 'force',
            'scope': 'read,activity:read_all'
        }
        if state:
            params['state'] = state

        return f'{self.BASE_URL}/oauth/authorize?{urlencode(params)}'

    def exchange_code(self, code):
        """Exchange authorization code for access token."""
        response = requests.post(
            f'{self.BASE_URL}/oauth/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': self.redirect_uri
            },
            timeout=STRAVA_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def refresh_token(self, refresh_token):
        """Refresh access token using refresh token."""
        response = requests.post(
            f'{self.BASE_URL}/oauth/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            },
            timeout=STRAVA_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    
    def is_token_valid(self, expires_at):
        """Check if access token is still valid."""
        return expires_at > int(time.time())
    
    def get_valid_token(self, access_token, refresh_token, expires_at):
        """Get a valid access token, refreshing if necessary."""
        if not refresh_token:
            # Email / file-import users have no Strava tokens at all.
            raise StravaNotConnected()
        if self.is_token_valid(expires_at):
            return access_token, refresh_token, expires_at
        
        token_data = self.refresh_token(refresh_token)
        return (
            token_data['access_token'],
            token_data['refresh_token'],
            token_data['expires_at']
        )
    
    def fetch_activities(self, access_token, after_timestamp=None, per_page=100):
        """Fetch user activities from Strava."""
        headers = {'Authorization': f'Bearer {access_token}'}
        activities = []
        page = 1
        
        while True:
            params = {'per_page': per_page, 'page': page}
            if after_timestamp:
                params['after'] = after_timestamp
            
            
            full_url = f'{self.API_URL}/athlete/activities'
            logger.debug(f"StravaService fetching from URL: {full_url} with params: {params}")

            response = requests.get(
                full_url,
                headers=headers,
                params=params,
                timeout=STRAVA_HTTP_TIMEOUT,
            )
            
            # Log response details if not successful
            if not response.ok:
                logger.warning(f"StravaService fetch_activities error. Status: {response.status_code}, Response: {response.text}")

            response.raise_for_status()
            data = response.json()
            
            if not data:
                break
            
            activities.extend(data)
            page += 1
        
        return activities
    
    def download_streams(self, activity_id, access_token):
        """Download activity streams from Strava in a single batched request.

        The Strava streams endpoint accepts a comma-separated ``keys`` list and
        returns all requested streams in one response. Issuing one request per
        key (as previously) multiplied the rate-limit budget and latency by N.
        """
        headers = {'Authorization': f'Bearer {access_token}'}
        stream_url = f'{self.API_URL}/activities/{activity_id}/streams'

        required_params = ['time', 'altitude', 'grade_smooth', 'velocity_smooth', 'latlng',
                           'heartrate', 'cadence', 'moving', 'distance', 'watts']

        params = {'keys': ','.join(required_params), 'key_by_type': 'true'}

        try:
            response = requests.get(
                stream_url,
                headers=headers,
                params=params,
                timeout=STRAVA_HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.warning(f"download_streams transport error for activity {activity_id}: {e}")
            return {param: [] for param in required_params}

        if response.status_code != 200:
            logger.warning(
                f"download_streams non-200 for activity {activity_id}: "
                f"status={response.status_code} body={response.text[:200]}"
            )
            return {param: [] for param in required_params}

        streams = response.json()
        return {
            param: streams.get(param, {}).get('data', [])
            for param in required_params
        }
    
    def filter_activities_by_length(self, activities, target_distance, tolerance=0.1):
        """Filter activities by distance with tolerance."""
        min_distance = target_distance * (1 - tolerance)
        max_distance = target_distance * (1 + tolerance)
        
        return [
            activity for activity in activities
            if min_distance <= activity.get('distance', 0) <= max_distance
        ]
    
    def get_timestamp_for_last_year(self):
        """Get Unix timestamp for one year ago (UTC)."""
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        return int(one_year_ago.timestamp())

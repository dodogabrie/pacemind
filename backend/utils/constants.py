"""Named constants for prediction scoring, thresholds, and confidence intervals."""

# --- Distance thresholds (meters) ---
LONG_ROUTE_THRESHOLD_M = 25_000
ULTRA_ROUTE_THRESHOLD_M = 40_000
LONG_RUN_THRESHOLD_M = 20_000
SHORT_WORKOUT_THRESHOLD_M = 15_000
ULTRA_RUN_THRESHOLD_M = 35_000

# --- Similarity scoring weights ---
DISTANCE_WEIGHT = 0.4
ELEVATION_WEIGHT = 0.3
EFFORT_WEIGHT = 0.3
SIMILARITY_RECOMMENDATION_THRESHOLD = 0.6

# --- Elevation calculation ---
ELEVATION_THRESHOLD_M = 0.5

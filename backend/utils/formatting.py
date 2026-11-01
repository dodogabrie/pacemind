"""Shared formatting utilities for the prediction pipeline."""


def format_seconds_to_hms(total_seconds: float) -> str:
    """Format a duration in seconds as 'H:MM:SS' or 'HH:MM:SS'."""
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_seconds_to_hms_padded(total_seconds: float) -> str:
    """Format a duration in seconds as 'HH:MM:SS' (zero-padded hours)."""
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def v_flat_to_pace(v_flat_ms: float) -> float:
    """Convert flat speed (m/s) to pace (min/km)."""
    return (1000.0 / v_flat_ms) / 60.0


def pace_to_v_flat(pace_min_per_km: float) -> float:
    """Convert pace (min/km) to flat speed (m/s)."""
    return 1000.0 / (pace_min_per_km * 60.0)


def classify_terrain(avg_grade: float) -> str:
    """Classify terrain type from average grade (as a fraction, e.g. 0.08 = 8%)."""
    if avg_grade > 0.08:
        return "Steep Climb"
    elif avg_grade > 0.03:
        return "Climb"
    elif avg_grade > -0.03:
        return "Flat"
    elif avg_grade > -0.08:
        return "Descent"
    else:
        return "Steep Descent"

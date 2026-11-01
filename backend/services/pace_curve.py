"""Pace-vs-grade helpers for one athlete's own streams (used by performance_tracker)."""
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

GRADE_BIN_WIDTH = 1  # percent
SMOOTH_WINDOW = 5
FLAT_BASE_RANGE = (-1.0, 1.0)  # percent
MIN_POINTS_PER_BIN = 10  # per activity bin
MAX_GRADE_ABS = 40
ANCHOR_GRADES = [-30, -20, -10, 0, 10, 20, 30]
ANCHOR_WINDOW = 2.0  # percent band around each anchor for user calibration


def _smooth_series(series: pd.Series, window: int = SMOOTH_WINDOW) -> pd.Series:
    return series.rolling(window=window, center=True, min_periods=1).mean()



def prepare_stream(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Clean and augment a single activity's stream."""
    if df is None or df.empty:
        return None
    if "moving" in df.columns and df["moving"].notna().any():
        df = df[df["moving"] == True]  # noqa: E712
    if df.empty:
        return None
    df = df.copy()
    df["velocity_smooth"] = _smooth_series(df["velocity_smooth"])
    df["grade_smooth"] = _smooth_series(df["grade_smooth"])
    df["velocity_kmh"] = df["velocity_smooth"] * 3.6
    df["pace_min_per_km"] = np.where(
        df["velocity_kmh"] > 0, 60.0 / df["velocity_kmh"], np.nan
    )
    df = df[np.isfinite(df["pace_min_per_km"]) & np.isfinite(df["grade_smooth"])]
    return df if not df.empty else None



def compute_flat_pace(df: pd.DataFrame) -> float:
    mask = df["grade_smooth"].between(*FLAT_BASE_RANGE, inclusive="both")
    if not mask.any():
        raise ValueError("No flat samples to compute flat pace.")
    flat_pace = df.loc[mask, "pace_min_per_km"].median()
    if not np.isfinite(flat_pace) or flat_pace <= 0:
        raise ValueError("Flat pace is not finite.")
    return float(flat_pace)


def compute_anchor_ratios(
    df: pd.DataFrame,
    flat_pace: float,
    anchors: Sequence[float] = ANCHOR_GRADES,
    window: float = ANCHOR_WINDOW,
) -> Dict[float, float]:
    ratios: Dict[float, float] = {}
    for anchor in anchors:
        mask = df["grade_smooth"].between(anchor - window, anchor + window, inclusive="both")
        if not mask.any():
            continue
        pace = df.loc[mask, "pace_min_per_km"].median()
        if np.isfinite(pace) and pace > 0:
            ratios[anchor] = pace / flat_pace
    return ratios


# ---- Personalization ----

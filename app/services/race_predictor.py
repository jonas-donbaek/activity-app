"""Race time predictor using Riegel formula and training data."""
import math
from datetime import date, timedelta
from typing import List, Optional

from app.models import Activity


def predict_half_marathon(activities: List[Activity]) -> Optional[dict]:
    """Predict half marathon time from recent training data.

    Uses Riegel formula: T2 = T1 * (D2/D1)^1.06
    Applied to best recent efforts at 5K, 10K, 15K distances.
    """
    target_m = 21097.5
    cutoff = date.today() - timedelta(days=60)  # last 60 days

    recent = [
        a for a in activities
        if a.distance_m >= 3000
        and a.moving_time_s > 0
        and _activity_date(a) >= cutoff
    ]

    if not recent:
        return None

    # Find best efforts at key distances
    predictions = []
    reference_efforts = []

    for ref_dist, label in [(5000, "5K"), (10000, "10K"), (15000, "15K")]:
        # Find activities close to this distance (within 20%)
        candidates = [
            a for a in recent
            if ref_dist * 0.8 <= a.distance_m <= ref_dist * 1.3
        ]
        if not candidates:
            continue

        # Best pace activity at this distance
        best = min(candidates, key=lambda a: a.moving_time_s / a.distance_m)
        best_time_s = best.moving_time_s
        best_dist_m = best.distance_m

        # Riegel formula
        predicted_s = best_time_s * (target_m / best_dist_m) ** 1.06
        predicted_min = predicted_s / 60

        predictions.append(predicted_min)
        reference_efforts.append({
            "distance": label,
            "name": best.name,
            "actual_dist_km": round(best_dist_m / 1000, 1),
            "time_min": round(best_time_s / 60, 1),
            "pace": _format_pace(best_time_s, best_dist_m),
            "predicted_hm": _format_time(predicted_min),
        })

    if not predictions:
        return None

    # Average prediction weighted towards longer distances (more reliable)
    if len(predictions) == 1:
        avg_min = predictions[0]
    else:
        # Weight: 5K=1, 10K=2, 15K=3
        weights = list(range(1, len(predictions) + 1))
        avg_min = sum(p * w for p, w in zip(predictions, weights)) / sum(weights)

    # Weekly volume adjustment: higher mileage improves endurance slightly
    weekly_km = _avg_weekly_km(activities, weeks=4)
    volume_factor = 1.0
    if weekly_km > 30:
        volume_factor = 0.98  # 2% bonus for good volume
    elif weekly_km < 15:
        volume_factor = 1.03  # 3% penalty for low volume

    adjusted_min = avg_min * volume_factor

    # Confidence range
    range_min = adjusted_min * 0.97
    range_max = adjusted_min * 1.05

    return {
        "predicted_time": _format_time(adjusted_min),
        "predicted_minutes": round(adjusted_min, 1),
        "predicted_pace": _format_pace(adjusted_min * 60, target_m),
        "range_fast": _format_time(range_min),
        "range_slow": _format_time(range_max),
        "reference_efforts": reference_efforts,
        "weekly_km": round(weekly_km, 1),
        "confidence": "high" if len(predictions) >= 2 else "moderate",
    }


def _activity_date(a: Activity) -> date:
    """Get date from activity start_date."""
    if hasattr(a.start_date, 'date'):
        return a.start_date.date()
    return a.start_date


def _avg_weekly_km(activities: List[Activity], weeks: int = 4) -> float:
    """Average weekly distance over last N weeks."""
    cutoff = date.today() - timedelta(weeks=weeks)
    recent_km = sum(
        a.distance_m / 1000
        for a in activities
        if _activity_date(a) >= cutoff
    )
    return recent_km / weeks


def _format_time(minutes: float) -> str:
    """Format minutes as H:MM:SS."""
    total_s = int(minutes * 60)
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_pace(time_s: float, distance_m: float) -> str:
    """Format pace as M:SS/km."""
    if distance_m <= 0:
        return "-"
    pace_s = time_s / (distance_m / 1000)
    m = int(pace_s // 60)
    s = int(pace_s % 60)
    return f"{m}:{s:02d}/km"

from datetime import date, datetime, timedelta
from typing import List, Optional

from app.models import Activity


def compute_weekly_summaries(activities: list[Activity]) -> list[dict]:
    """Aggregate activities by ISO week and compute summaries."""
    if not activities:
        return []

    # Group by ISO week
    weeks: dict[str, list[Activity]] = {}
    for act in activities:
        # Get Monday of the week
        if isinstance(act.start_date, datetime):
            dt = act.start_date.date()
        elif isinstance(act.start_date, date):
            dt = act.start_date
        else:
            dt = date.today()
        monday = dt - timedelta(days=dt.weekday())
        key = monday.isoformat()
        weeks.setdefault(key, []).append(act)

    # Build continuous range from first to current week (fill gaps with 0)
    sorted_keys = sorted(weeks.keys())
    first_monday = date.fromisoformat(sorted_keys[0])
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())

    all_mondays = []
    m = first_monday
    while m <= current_monday:
        all_mondays.append(m.isoformat())
        m += timedelta(days=7)

    summaries = []
    prev_distance = None

    for week_start_str in all_mondays:
        acts = weeks.get(week_start_str, [])
        week_start = date.fromisoformat(week_start_str)
        week_end = week_start + timedelta(days=6)

        total_distance_m = sum(a.distance_m for a in acts)
        total_time_s = sum(a.moving_time_s for a in acts)
        total_km = round(total_distance_m / 1000, 2)
        num_runs = len(acts)

        # Zone distribution (weighted by activity duration)
        total_duration_with_zones = sum(
            a.moving_time_s for a in acts if a.analyzed and a.zone1_pct is not None
        )

        zone_dist = {}
        if total_duration_with_zones > 0:
            for zone in range(1, 6):
                weighted_pct = sum(
                    getattr(a, f"zone{zone}_pct", 0) * a.moving_time_s
                    for a in acts
                    if a.analyzed and getattr(a, f"zone{zone}_pct") is not None
                ) / total_duration_with_zones
                zone_dist[f"zone{zone}"] = round(weighted_pct, 1)

        # Mileage increase warning
        increase_pct = None
        injury_warning = False
        if prev_distance and prev_distance > 0:
            increase_pct = round((total_distance_m - prev_distance) / prev_distance * 100, 1)
            injury_warning = increase_pct > 10

        # Flags from activities
        week_flags = []
        for a in acts:
            if a.flags:
                for flag in a.flags.split(","):
                    if flag and flag not in week_flags:
                        week_flags.append(flag)

        summaries.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "week_iso": week_start.isocalendar()[1],
                "total_km": total_km,
                "total_time_min": round(total_time_s / 60, 1),
                "num_runs": num_runs,
                "avg_pace_min_km": round((total_time_s / 60) / total_km, 2)
                if total_km > 0
                else None,
                "zone_distribution": zone_dist if zone_dist else None,
                "increase_pct": increase_pct,
                "injury_warning": injury_warning,
                "flags": week_flags,
            }
        )

        prev_distance = total_distance_m

    return summaries


def compute_recovery_status(activities: List[Activity]) -> dict:
    """Compute recovery status based on last 7 days of training.

    Returns dict with status, emoji, color, message, and recommendation.
    """
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    fourteen_days_ago = today - timedelta(days=14)

    # Split activities into last 7 days and previous 7 days
    recent = []
    previous = []
    for a in activities:
        dt = a.start_date.date() if isinstance(a.start_date, datetime) else a.start_date
        if seven_days_ago <= dt <= today:
            recent.append(a)
        elif fourteen_days_ago <= dt < seven_days_ago:
            previous.append(a)

    # Compute load for recent week
    recent_km = sum(a.distance_m for a in recent) / 1000
    recent_effort = sum(a.effort_score or 0 for a in recent)
    recent_runs = len(recent)

    # Compute load for previous week
    prev_km = sum(a.distance_m for a in previous) / 1000
    prev_effort = sum(a.effort_score or 0 for a in previous)

    # Days since last run
    days_since_last = None
    if recent:
        last_run_date = max(
            a.start_date.date() if isinstance(a.start_date, datetime) else a.start_date
            for a in recent
        )
        days_since_last = (today - last_run_date).days

    # Determine status
    if recent_runs == 0:
        return {
            "status": "Hvileuge",
            "emoji": "😴",
            "color": "#9E9E9E",
            "load_7d_km": 0,
            "load_7d_effort": 0,
            "days_since_last": days_since_last,
            "message": "Du har ikke løbet i denne uge. Hvil er også træning!",
            "recommendation": "Tid til en rolig Easy Run for at holde kroppen i gang.",
        }

    # Load ratio compared to previous week
    load_ratio = recent_effort / prev_effort if prev_effort > 0 else 1.0

    if days_since_last is not None and days_since_last >= 2 and load_ratio < 0.8:
        status = "Frisk og klar"
        emoji = "🟢"
        color = "#4CAF50"
        message = f"{recent_km:.0f} km denne uge med god restitution."
        recommendation = "Du er klar til en hårdere session - interval eller tempo!"
    elif load_ratio > 1.3 or recent_effort > 250:
        status = "Tag en hviledag"
        emoji = "🔴"
        color = "#f44336"
        message = f"Høj belastning: {recent_km:.0f} km / effort {recent_effort} de sidste 7 dage."
        recommendation = "Din krop har brug for hvile. Tag en dag fri eller en meget let tur (Zone 1)."
    elif load_ratio > 1.0 or (days_since_last is not None and days_since_last == 0):
        status = "Let træt"
        emoji = "🟡"
        color = "#FF9800"
        message = f"{recent_km:.0f} km denne uge. Kroppen arbejder på at restituere."
        recommendation = "Hold dig til en Easy Run i Zone 2 i dag. Ingen intervaltræning."
    else:
        status = "Frisk og klar"
        emoji = "🟢"
        color = "#4CAF50"
        message = f"{recent_km:.0f} km denne uge - god balance."
        recommendation = "Du kan træne som planlagt!"

    return {
        "status": status,
        "emoji": emoji,
        "color": color,
        "load_7d_km": round(recent_km, 1),
        "load_7d_effort": recent_effort,
        "days_since_last": days_since_last,
        "message": message,
        "recommendation": recommendation,
    }

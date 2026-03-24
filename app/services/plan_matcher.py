"""Auto-match Strava activities to planned workouts."""
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Activity, PlannedWorkout, TrainingPlanWeek


def classify_workout_type(activity: Activity) -> str:
    """Classify an activity as long_run, interval, or easy based on data."""
    name_lower = activity.name.lower()
    distance_km = activity.distance_m / 1000

    # Check name hints first
    long_keywords = ["long run", "lang tur", "langtur", "long"]
    interval_keywords = ["interval", "tempo", "fart", "speed", "threshold", "fartlek"]

    if any(kw in name_lower for kw in long_keywords):
        return "long_run"
    if any(kw in name_lower for kw in interval_keywords):
        return "interval"

    # Use HR zone data if available
    if activity.analyzed and activity.zone4_pct is not None:
        high_intensity_pct = (activity.zone4_pct or 0) + (activity.zone5_pct or 0)
        if high_intensity_pct > 30:
            return "interval"

    # Use distance as heuristic
    if distance_km >= 12:
        return "long_run"
    elif distance_km <= 8:
        return "easy"

    return "easy"


async def match_activities_to_plan(db: AsyncSession) -> dict:
    """Match all unmatched activities to planned workouts.

    Returns stats about matching.
    """
    # Get all plan weeks
    plan_result = await db.execute(
        select(TrainingPlanWeek).order_by(TrainingPlanWeek.week_number)
    )
    plan_weeks = plan_result.scalars().all()
    if not plan_weeks:
        return {"matched": 0, "message": "Ingen træningsplan fundet"}

    # Get all planned workouts
    workout_result = await db.execute(
        select(PlannedWorkout).where(PlannedWorkout.completed == False)
    )
    planned_workouts = workout_result.scalars().all()

    # Get unmatched activities
    activity_result = await db.execute(
        select(Activity)
        .where(Activity.matched_workout_type == None)
        .order_by(Activity.start_date.asc())
    )
    activities = activity_result.scalars().all()

    matched_count = 0
    updated_weeks = set()

    for activity in activities:
        act_date = activity.start_date.date() if isinstance(activity.start_date, datetime) else activity.start_date
        workout_type = classify_workout_type(activity)
        activity.matched_workout_type = workout_type

        # Find matching planned workout (same type, within 1 day)
        best_match = None
        for pw in planned_workouts:
            if pw.completed:
                continue
            if pw.workout_type == "rest":
                continue
            day_diff = abs((act_date - pw.workout_date).days)
            if day_diff <= 1 and pw.workout_type == workout_type:
                best_match = pw
                break
            # Fallback: any non-rest workout within 1 day
            if day_diff <= 1 and best_match is None:
                best_match = pw

        if best_match:
            best_match.completed = True
            best_match.matched_activity_id = activity.id
            matched_count += 1

        # Update week stats
        for week in plan_weeks:
            if week.start_date <= act_date <= week.end_date:
                updated_weeks.add(week.id)
                break

    # Recompute completed_km and completed_runs for affected weeks
    for week in plan_weeks:
        if week.id in updated_weeks:
            week_activities = await db.execute(
                select(Activity).where(
                    and_(
                        Activity.start_date >= datetime.combine(week.start_date, datetime.min.time()),
                        Activity.start_date <= datetime.combine(week.end_date, datetime.max.time()),
                    )
                )
            )
            week_acts = week_activities.scalars().all()
            week.completed_km = round(sum(a.distance_m for a in week_acts) / 1000, 1)
            week.completed_runs = len(week_acts)

    await db.commit()
    return {"matched": matched_count, "total_activities": len(activities)}

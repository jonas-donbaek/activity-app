from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Activity, TrainingPlanWeek
from app.services import shoe_tracker, token_manager, weekly_summary

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _base_context(request: Request, authenticated: bool = False) -> dict:
    race_date = date.fromisoformat(settings.race_date)
    days_to_race = (race_date - date.today()).days
    return {
        "request": request,
        "authenticated": authenticated,
        "race_name": settings.race_name,
        "race_date": settings.race_date,
        "days_to_race": max(days_to_race, 0),
    }


@router.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse("/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = await token_manager.get_tokens(db)
    ctx = _base_context(request, authenticated=token is not None)

    if token:
        ctx["athlete_name"] = token.athlete_name or "Runner"

        # Latest activity
        result = await db.execute(
            select(Activity).order_by(Activity.start_date.desc()).limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest:
            ctx["latest_activity"] = {
                "id": latest.id,
                "name": latest.name,
                "distance_km": round(latest.distance_m / 1000, 2),
                "moving_time_min": round(latest.moving_time_s / 60, 1),
                "avg_heartrate": latest.avg_heartrate,
                "pace_min_km": round(
                    (latest.moving_time_s / 60) / (latest.distance_m / 1000), 2
                )
                if latest.distance_m > 0
                else None,
                "zones": {
                    "zone1": latest.zone1_pct,
                    "zone2": latest.zone2_pct,
                    "zone3": latest.zone3_pct,
                    "zone4": latest.zone4_pct,
                    "zone5": latest.zone5_pct,
                }
                if latest.analyzed
                else None,
                "flags": latest.flags.split(",") if latest.flags else [],
                "coach_comment": latest.coach_comment,
            }
        else:
            ctx["latest_activity"] = None

        # Weekly summaries
        all_activities = await db.execute(
            select(Activity).order_by(Activity.start_date.asc())
        )
        activities = all_activities.scalars().all()
        summaries = weekly_summary.compute_weekly_summaries(activities)
        ctx["weekly_summaries"] = summaries

        # Current week
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        current_week_key = monday.isoformat()
        ctx["current_week"] = next(
            (w for w in summaries if w["week_start"] == current_week_key), None
        )

        # Current training plan week
        plan_result = await db.execute(
            select(TrainingPlanWeek).where(
                TrainingPlanWeek.start_date <= today,
                TrainingPlanWeek.end_date >= today,
            )
        )
        ctx["current_plan_week"] = plan_result.scalar_one_or_none()
        ctx["current_week_plan"] = ctx["current_plan_week"]

        # Recovery status
        from app.services.weekly_summary import compute_recovery_status
        ctx["recovery"] = compute_recovery_status(activities)

        # Today's workout
        from app.models import PlannedWorkout
        today_workout_result = await db.execute(
            select(PlannedWorkout).where(PlannedWorkout.workout_date == today)
        )
        ctx["today_workout"] = today_workout_result.scalar_one_or_none()

        # Plan weeks for chart - compute actual km from activities
        all_plan_weeks = await db.execute(
            select(TrainingPlanWeek).order_by(TrainingPlanWeek.week_number)
        )
        plan_weeks_list = all_plan_weeks.scalars().all()
        plan_chart = []
        for w in plan_weeks_list:
            # Sum actual activity km within this week's date range
            from datetime import datetime as dt
            actual_km = round(sum(
                a.distance_m for a in activities
                if w.start_date <= (a.start_date.date() if isinstance(a.start_date, dt) else a.start_date) <= w.end_date
            ) / 1000, 1)
            plan_chart.append({
                "week_number": w.week_number,
                "target_km": w.total_target_km,
                "completed_km": actual_km,
                "is_current": w.start_date <= today <= w.end_date,
                "is_past": w.end_date < today,
            })
        ctx["plan_chart_weeks"] = plan_chart

        # Race prediction
        from app.services.race_predictor import predict_half_marathon
        ctx["race_prediction"] = predict_half_marathon(activities)

        # Shoes
        ctx["shoes"] = await shoe_tracker.get_shoe_status(db)
    else:
        ctx["weekly_summaries"] = []

    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/dashboard/activity/{activity_id}", response_class=HTMLResponse)
async def activity_detail(
    request: Request, activity_id: int, db: AsyncSession = Depends(get_db)
):
    from app.services.activity_analyzer import decompress_streams

    token = await token_manager.get_tokens(db)
    ctx = _base_context(request, authenticated=token is not None)

    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    a = result.scalar_one_or_none()
    if not a:
        return HTMLResponse("<h1>Aktivitet ikke fundet</h1>", status_code=404)

    activity_data = {
        "id": a.id,
        "name": a.name,
        "sport_type": a.sport_type,
        "start_date": a.start_date.isoformat(),
        "distance_km": round(a.distance_m / 1000, 2),
        "moving_time_min": round(a.moving_time_s / 60, 1),
        "pace_min_km": round((a.moving_time_s / 60) / (a.distance_m / 1000), 2)
        if a.distance_m > 0
        else None,
        "avg_heartrate": a.avg_heartrate,
        "max_heartrate": a.max_heartrate,
        "avg_cadence": a.avg_cadence,
        "total_elevation": a.total_elevation,
        "pace_cv": a.pace_cv,
        "zones": {
            "zone1": a.zone1_pct,
            "zone2": a.zone2_pct,
            "zone3": a.zone3_pct,
            "zone4": a.zone4_pct,
            "zone5": a.zone5_pct,
        }
        if a.analyzed
        else None,
        "flags": a.flags.split(",") if a.flags else [],
        "coach_comment": a.coach_comment,
        "effort_score": a.effort_score,
        "matched_workout_type": a.matched_workout_type,
        "zone1_seconds": a.zone1_seconds or 0,
        "zone2_seconds": a.zone2_seconds or 0,
        "zone3_seconds": a.zone3_seconds or 0,
        "zone4_seconds": a.zone4_seconds or 0,
        "zone5_seconds": a.zone5_seconds or 0,
        "streams": None,
    }

    if a.raw_streams:
        try:
            activity_data["streams"] = decompress_streams(a.raw_streams)
            # Compute splits if distance stream available
            from app.services.activity_analyzer import compute_splits, compute_pace_zones
            splits = compute_splits(activity_data["streams"])
            if splits:
                activity_data["splits"] = splits
            # Compute pace zones
            vel_stream = activity_data["streams"].get("velocity_smooth", {}).get("data", [])
            time_stream = activity_data["streams"].get("time", {}).get("data", [])
            if vel_stream:
                pace_zones = compute_pace_zones(vel_stream, time_stream or None)
                if pace_zones:
                    activity_data["pace_zones"] = pace_zones
        except Exception:
            pass

    ctx["activity"] = activity_data
    return templates.TemplateResponse("activity_detail.html", ctx)


@router.get("/dashboard/plan", response_class=HTMLResponse)
async def plan_page(request: Request, db: AsyncSession = Depends(get_db)):
    token = await token_manager.get_tokens(db)
    ctx = _base_context(request, authenticated=token is not None)

    result = await db.execute(
        select(TrainingPlanWeek).order_by(TrainingPlanWeek.week_number)
    )
    weeks = result.scalars().all()

    today = date.today()
    plan_weeks = []
    for w in weeks:
        plan_weeks.append(
            {
                "week_number": w.week_number,
                "start_date": w.start_date.isoformat(),
                "end_date": w.end_date.isoformat(),
                "phase": w.phase,
                "long_run_km": w.long_run_km,
                "interval_description": w.interval_description,
                "easy_runs_km": w.easy_runs_km,
                "total_target_km": w.total_target_km,
                "completed_km": w.completed_km,
                "completed_runs": w.completed_runs,
                "is_current": w.start_date <= today <= w.end_date,
                "is_past": w.end_date < today,
            }
        )

    ctx["plan_weeks"] = plan_weeks
    return templates.TemplateResponse("plan.html", ctx)


@router.get("/dashboard/today", response_class=HTMLResponse)
async def today_page(request: Request, db: AsyncSession = Depends(get_db)):
    token = await token_manager.get_tokens(db)
    ctx = _base_context(request, authenticated=token is not None)

    from app.models import PlannedWorkout
    today = date.today()

    # Today's workout
    today_result = await db.execute(
        select(PlannedWorkout).where(PlannedWorkout.workout_date == today)
    )
    ctx["today_workout"] = today_result.scalar_one_or_none()

    # This week's workouts
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_result = await db.execute(
        select(PlannedWorkout).where(
            PlannedWorkout.workout_date >= monday,
            PlannedWorkout.workout_date <= sunday,
        ).order_by(PlannedWorkout.day_of_week)
    )
    ctx["week_workouts"] = week_result.scalars().all()
    ctx["today_date"] = today

    # Recovery status
    all_activities = await db.execute(
        select(Activity).order_by(Activity.start_date.asc())
    )
    activities = all_activities.scalars().all()
    from app.services.weekly_summary import compute_recovery_status
    ctx["recovery"] = compute_recovery_status(activities)

    return templates.TemplateResponse("today.html", ctx)


@router.get("/dashboard/shoes", response_class=HTMLResponse)
async def shoes_page(request: Request, db: AsyncSession = Depends(get_db)):
    token = await token_manager.get_tokens(db)
    ctx = _base_context(request, authenticated=token is not None)
    ctx["shoes"] = await shoe_tracker.get_shoe_status(db)
    return templates.TemplateResponse("shoes.html", ctx)

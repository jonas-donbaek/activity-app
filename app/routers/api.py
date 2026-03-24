from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException


def _parse_date(s: str) -> datetime:
    """Parse a date string from Strava, handling various ISO formats."""
    s = s.replace("Z", "")
    # Remove timezone offset for naive datetime
    if "+" in s:
        s = s[: s.index("+")]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Activity, Shoe, TrainingPlanWeek
from app.services import activity_analyzer, strava_client, token_manager

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/activities/sync")
async def sync_activities(db: AsyncSession = Depends(get_db)):
    """Fetch recent activities from Strava, analyze them, and store results."""
    access_token = await token_manager.get_valid_access_token(db)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated with Strava")

    # Sync HR zones from Strava
    try:
        zones_data = await strava_client.get_athlete_zones(access_token)
        hr_zone_list = zones_data.get("heart_rate", {}).get("zones", [])
        if hr_zone_list and len(hr_zone_list) >= 5:
            from app.config import settings as app_settings
            app_settings.zone1_ceiling = hr_zone_list[0]["max"]
            app_settings.zone2_ceiling = hr_zone_list[1]["max"]
            app_settings.zone3_ceiling = hr_zone_list[2]["max"]
            app_settings.zone4_ceiling = hr_zone_list[3]["max"]
    except Exception:
        pass  # Continue sync even if zone fetch fails

    activities = await strava_client.get_activities(access_token, per_page=30)
    synced = 0
    analyzed = 0

    for act in activities:
        activity_id = act["id"]
        sport_type = act.get("sport_type", act.get("type", ""))

        # Skip non-run activities
        if sport_type not in ("Run", "TrailRun", "VirtualRun"):
            continue

        # Check if already stored
        existing = await db.execute(select(Activity).where(Activity.id == activity_id))
        if existing.scalar_one_or_none():
            continue

        # Store the activity
        activity = Activity(
            id=activity_id,
            athlete_id=act.get("athlete", {}).get("id", 0),
            name=act.get("name", ""),
            sport_type=sport_type,
            start_date=_parse_date(act["start_date_local"]),
            distance_m=act.get("distance", 0.0),
            moving_time_s=act.get("moving_time", 0),
            elapsed_time_s=act.get("elapsed_time", 0),
            avg_heartrate=act.get("average_heartrate"),
            max_heartrate=act.get("max_heartrate"),
            avg_speed=act.get("average_speed", 0.0),
            avg_cadence=act.get("average_cadence"),
            total_elevation=act.get("total_elevation_gain", 0.0),
            gear_id=act.get("gear_id"),
        )
        db.add(activity)
        synced += 1

        # Fetch streams and analyze
        try:
            streams = await strava_client.get_activity_streams(access_token, activity_id)
            if streams:
                result = activity_analyzer.analyze_activity(
                    name=activity.name,
                    distance_m=activity.distance_m,
                    avg_hr=activity.avg_heartrate,
                    streams=streams,
                )
                activity.zone1_pct = result.zone1_pct
                activity.zone2_pct = result.zone2_pct
                activity.zone3_pct = result.zone3_pct
                activity.zone4_pct = result.zone4_pct
                activity.zone5_pct = result.zone5_pct
                activity.zone1_seconds = result.zone1_seconds
                activity.zone2_seconds = result.zone2_seconds
                activity.zone3_seconds = result.zone3_seconds
                activity.zone4_seconds = result.zone4_seconds
                activity.zone5_seconds = result.zone5_seconds
                activity.pace_cv = result.pace_cv
                activity.flags = ",".join(result.flags) if result.flags else None
                activity.coach_comment = result.coach_comment
                activity.raw_streams = activity_analyzer.compress_streams(streams)
                activity.analyzed = True
                activity.effort_score = result.effort_score
                analyzed += 1
        except Exception:
            pass  # Store activity anyway, analyze later

    await db.commit()

    # Auto-match activities to training plan
    from app.services.plan_matcher import match_activities_to_plan
    match_result = await match_activities_to_plan(db)

    return {
        "synced": synced,
        "analyzed": analyzed,
        "matched": match_result.get("matched", 0),
        "total_fetched": len(activities),
    }


@router.get("/activities")
async def list_activities(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List stored activities with analysis results."""
    result = await db.execute(
        select(Activity).order_by(Activity.start_date.desc()).limit(limit)
    )
    activities = result.scalars().all()

    return [
        {
            "id": a.id,
            "name": a.name,
            "sport_type": a.sport_type,
            "start_date": a.start_date.isoformat(),
            "distance_km": round(a.distance_m / 1000, 2),
            "moving_time_min": round(a.moving_time_s / 60, 1),
            "avg_heartrate": a.avg_heartrate,
            "pace_min_km": round((a.moving_time_s / 60) / (a.distance_m / 1000), 2)
            if a.distance_m > 0
            else None,
            "zones": {
                "zone1": a.zone1_pct,
                "zone2": a.zone2_pct,
                "zone3": a.zone3_pct,
                "zone4": a.zone4_pct,
                "zone5": a.zone5_pct,
            }
            if a.analyzed
            else None,
            "pace_cv": a.pace_cv,
            "flags": a.flags.split(",") if a.flags else [],
            "coach_comment": a.coach_comment,
            "analyzed": a.analyzed,
        }
        for a in activities
    ]


@router.get("/activities/{activity_id}")
async def get_activity(activity_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single activity with full details."""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")

    data = {
        "id": a.id,
        "name": a.name,
        "sport_type": a.sport_type,
        "start_date": a.start_date.isoformat(),
        "distance_km": round(a.distance_m / 1000, 2),
        "moving_time_min": round(a.moving_time_s / 60, 1),
        "elapsed_time_min": round(a.elapsed_time_s / 60, 1),
        "avg_heartrate": a.avg_heartrate,
        "max_heartrate": a.max_heartrate,
        "avg_speed_kmh": round(a.avg_speed * 3.6, 2),
        "pace_min_km": round((a.moving_time_s / 60) / (a.distance_m / 1000), 2)
        if a.distance_m > 0
        else None,
        "avg_cadence": a.avg_cadence,
        "total_elevation": a.total_elevation,
        "zones": {
            "zone1": a.zone1_pct,
            "zone2": a.zone2_pct,
            "zone3": a.zone3_pct,
            "zone4": a.zone4_pct,
            "zone5": a.zone5_pct,
        }
        if a.analyzed
        else None,
        "pace_cv": a.pace_cv,
        "flags": a.flags.split(",") if a.flags else [],
        "coach_comment": a.coach_comment,
        "analyzed": a.analyzed,
    }

    # Include decompressed streams if available
    if a.raw_streams:
        try:
            data["streams"] = activity_analyzer.decompress_streams(a.raw_streams)
        except Exception:
            data["streams"] = None

    return data


@router.get("/weekly")
async def weekly_summary(db: AsyncSession = Depends(get_db)):
    """Get weekly training summaries with mileage warnings."""
    from app.services.weekly_summary import compute_weekly_summaries

    result = await db.execute(select(Activity).order_by(Activity.start_date.asc()))
    activities = result.scalars().all()
    return compute_weekly_summaries(activities)


@router.get("/plan")
async def get_plan(db: AsyncSession = Depends(get_db)):
    """Get the training plan."""
    result = await db.execute(
        select(TrainingPlanWeek).order_by(TrainingPlanWeek.week_number)
    )
    weeks = result.scalars().all()

    return [
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
        }
        for w in weeks
    ]


@router.post("/plan/generate")
async def generate_plan(db: AsyncSession = Depends(get_db)):
    """Generate or regenerate the training plan with daily workouts."""
    from app.services.training_plan import generate_daily_workouts, generate_training_plan

    from sqlalchemy import delete

    from app.models import PlannedWorkout

    await db.execute(delete(PlannedWorkout))
    await db.execute(delete(TrainingPlanWeek))
    await db.flush()

    weeks = generate_training_plan()
    for w in weeks:
        db.add(w)
    await db.flush()  # Get IDs assigned

    total_workouts = 0
    for w in weeks:
        workouts = generate_daily_workouts(w)
        for wo in workouts:
            wo.week_id = w.id
            db.add(wo)
        total_workouts += len(workouts)

    await db.commit()

    # Auto-match existing activities
    from app.services.plan_matcher import match_activities_to_plan
    await match_activities_to_plan(db)

    return {
        "message": f"Plan genereret: {len(weeks)} uger, {total_workouts} workouts",
        "weeks": len(weeks),
        "workouts": total_workouts,
    }


@router.get("/activities/{activity_id}/description")
async def get_activity_description(activity_id: int, db: AsyncSession = Depends(get_db)):
    """Generate a Strava description for copy-paste."""
    result = await db.execute(select(Activity).where(Activity.id == activity_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Build analysis result from stored data
    from app.services.activity_analyzer import AnalysisResult, generate_strava_description

    analysis = AnalysisResult(
        zone1_pct=a.zone1_pct or 0,
        zone2_pct=a.zone2_pct or 0,
        zone3_pct=a.zone3_pct or 0,
        zone4_pct=a.zone4_pct or 0,
        zone5_pct=a.zone5_pct or 0,
        pace_cv=a.pace_cv,
        effort_score=a.effort_score,
        coach_comment=a.coach_comment or "",
    )

    # Get plan week info
    from datetime import date as date_type
    act_date = a.start_date.date() if hasattr(a.start_date, 'date') else a.start_date
    plan_result = await db.execute(
        select(TrainingPlanWeek).where(
            TrainingPlanWeek.start_date <= act_date,
            TrainingPlanWeek.end_date >= act_date,
        )
    )
    plan_week = plan_result.scalar_one_or_none()
    total_weeks_result = await db.execute(select(TrainingPlanWeek))
    total_weeks = len(total_weeks_result.scalars().all())

    description = generate_strava_description(
        name=a.name,
        distance_m=a.distance_m,
        moving_time_s=a.moving_time_s,
        avg_hr=a.avg_heartrate,
        result=analysis,
        plan_week=plan_week.week_number if plan_week else None,
        plan_total_weeks=total_weeks if total_weeks else None,
    )

    return {"description": description}


@router.get("/today")
async def todays_workout(db: AsyncSession = Depends(get_db)):
    """Get today's planned workout."""
    from datetime import date as date_type

    from app.models import PlannedWorkout

    today = date_type.today()
    result = await db.execute(
        select(PlannedWorkout).where(PlannedWorkout.workout_date == today)
    )
    workout = result.scalar_one_or_none()

    if not workout:
        return {"workout": None, "message": "Ingen planlagt workout i dag"}

    return {
        "workout": {
            "title": workout.title,
            "type": workout.workout_type,
            "description": workout.description,
            "target_distance_km": workout.target_distance_km,
            "target_pace_range": workout.target_pace_range,
            "target_hr_zone": workout.target_hr_zone,
            "completed": workout.completed,
            "date": workout.workout_date.isoformat(),
        }
    }


@router.get("/shoes")
async def list_shoes(db: AsyncSession = Depends(get_db)):
    """Get shoe status."""
    result = await db.execute(select(Shoe).where(Shoe.active == True))
    shoes = result.scalars().all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "strava_gear_id": s.strava_gear_id,
            "total_distance_km": round(s.total_distance_m / 1000, 1),
            "warn_at_km": round(s.warn_distance_m / 1000, 0),
            "retire_at_km": round(s.retire_distance_m / 1000, 0),
            "status": "retired"
            if s.total_distance_m >= s.retire_distance_m
            else "warning"
            if s.total_distance_m >= s.warn_distance_m
            else "ok",
        }
        for s in shoes
    ]


@router.post("/shoes")
async def add_shoe(
    name: str,
    strava_gear_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Add a new shoe."""
    shoe = Shoe(name=name, strava_gear_id=strava_gear_id)
    db.add(shoe)
    await db.commit()
    return {"id": shoe.id, "name": shoe.name}


@router.get("/race-prediction")
async def race_prediction(db: AsyncSession = Depends(get_db)):
    """Predict half marathon time from training data."""
    from app.services.race_predictor import predict_half_marathon

    result = await db.execute(select(Activity).order_by(Activity.start_date.asc()))
    activities = result.scalars().all()
    prediction = predict_half_marathon(activities)
    if not prediction:
        return {"prediction": None, "message": "Ikke nok data til forudsigelse"}
    return prediction


@router.post("/activities/reanalyze")
async def reanalyze_activities(db: AsyncSession = Depends(get_db)):
    """Re-analyze all activities with current HR zone settings."""
    result = await db.execute(select(Activity).where(Activity.raw_streams.isnot(None)))
    activities = result.scalars().all()
    reanalyzed = 0

    for activity in activities:
        try:
            streams = activity_analyzer.decompress_streams(activity.raw_streams)
            analysis = activity_analyzer.analyze_activity(
                name=activity.name,
                distance_m=activity.distance_m,
                avg_hr=activity.avg_heartrate,
                streams=streams,
            )
            activity.zone1_pct = analysis.zone1_pct
            activity.zone2_pct = analysis.zone2_pct
            activity.zone3_pct = analysis.zone3_pct
            activity.zone4_pct = analysis.zone4_pct
            activity.zone5_pct = analysis.zone5_pct
            activity.zone1_seconds = analysis.zone1_seconds
            activity.zone2_seconds = analysis.zone2_seconds
            activity.zone3_seconds = analysis.zone3_seconds
            activity.zone4_seconds = analysis.zone4_seconds
            activity.zone5_seconds = analysis.zone5_seconds
            activity.pace_cv = analysis.pace_cv
            activity.flags = ",".join(analysis.flags) if analysis.flags else None
            activity.coach_comment = analysis.coach_comment
            activity.effort_score = analysis.effort_score
            reanalyzed += 1
        except Exception:
            pass

    await db.commit()
    return {"reanalyzed": reanalyzed, "total": len(activities)}


@router.post("/zones/sync")
async def sync_zones(db: AsyncSession = Depends(get_db)):
    """Fetch HR zones from Strava and update app settings."""
    access_token = await token_manager.get_valid_access_token(db)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated with Strava")

    zones_data = await strava_client.get_athlete_zones(access_token)

    # Strava returns zones as list of {min, max} dicts
    hr_zone_list = zones_data.get("heart_rate", {}).get("zones", [])
    if not hr_zone_list or len(hr_zone_list) < 5:
        raise HTTPException(status_code=400, detail="Kunne ikke hente zoner fra Strava")

    # Zone boundaries: Z1 max, Z2 max, Z3 max, Z4 max
    z1_ceiling = hr_zone_list[0]["max"]
    z2_ceiling = hr_zone_list[1]["max"]
    z3_ceiling = hr_zone_list[2]["max"]
    z4_ceiling = hr_zone_list[3]["max"]

    # Update runtime settings
    from app.config import settings as app_settings
    app_settings.zone1_ceiling = z1_ceiling
    app_settings.zone2_ceiling = z2_ceiling
    app_settings.zone3_ceiling = z3_ceiling
    app_settings.zone4_ceiling = z4_ceiling

    # Persist to .env file
    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_lines = f.readlines()

    # Update or add zone settings
    zone_keys = {
        "ZONE1_CEILING": str(z1_ceiling),
        "ZONE2_CEILING": str(z2_ceiling),
        "ZONE3_CEILING": str(z3_ceiling),
        "ZONE4_CEILING": str(z4_ceiling),
    }
    updated_keys = set()
    new_lines = []
    for line in env_lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in zone_keys:
            new_lines.append(f"{key}={zone_keys[key]}\n")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, val in zone_keys.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    return {
        "message": "Zoner opdateret fra Strava",
        "zones": {
            "zone1_ceiling": z1_ceiling,
            "zone2_ceiling": z2_ceiling,
            "zone3_ceiling": z3_ceiling,
            "zone4_ceiling": z4_ceiling,
        },
    }

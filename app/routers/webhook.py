from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.services import activity_analyzer, strava_client, token_manager

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.get("")
async def webhook_validate(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    """Strava webhook subscription validation."""
    if hub_mode == "subscribe" and hub_verify_token == settings.webhook_verify_token:
        return {"hub.challenge": hub_challenge}
    return {"error": "Invalid verify token"}, 403


@router.post("")
async def webhook_event(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming Strava webhook events."""
    body = await request.json()

    object_type = body.get("object_type")
    aspect_type = body.get("aspect_type")
    object_id = body.get("object_id")

    # Only process new/updated activities
    if object_type == "activity" and aspect_type in ("create", "update"):
        background_tasks.add_task(process_activity, object_id)

    return {"status": "ok"}


async def process_activity(activity_id: int):
    """Background task: fetch and analyze a new activity."""
    from datetime import datetime

    from sqlalchemy import select

    from app.routers.api import _parse_date

    from app.models import Activity

    async with async_session() as db:
        access_token = await token_manager.get_valid_access_token(db)
        if not access_token:
            return

        try:
            act = await strava_client.get_activity(access_token, activity_id)
        except Exception:
            return

        sport_type = act.get("sport_type", act.get("type", ""))
        if sport_type not in ("Run", "TrailRun", "VirtualRun"):
            return

        # Check if already exists
        existing = await db.execute(select(Activity).where(Activity.id == activity_id))
        activity = existing.scalar_one_or_none()

        if not activity:
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
                activity.pace_cv = result.pace_cv
                activity.flags = ",".join(result.flags) if result.flags else None
                activity.coach_comment = result.coach_comment
                activity.raw_streams = activity_analyzer.compress_streams(streams)
                activity.analyzed = True
        except Exception:
            pass

        await db.commit()

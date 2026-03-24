from typing import List, Optional

import httpx

from app.config import settings

STRAVA_API_BASE = "https://www.strava.com/api/v3"


async def exchange_token(code: str) -> dict:
    """Exchange authorization code for access/refresh tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_activities(
    access_token: str, page: int = 1, per_page: int = 50, after: Optional[int] = None
) -> List[dict]:
    """Fetch athlete activities."""
    params: dict = {"page": page, "per_page": per_page}
    if after:
        params["after"] = after

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_activity(access_token: str, activity_id: int) -> dict:
    """Fetch a single activity detail."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_activity_streams(
    access_token: str,
    activity_id: int,
    stream_types: str = "heartrate,velocity_smooth,cadence,altitude,time,distance",
) -> dict:
    """Fetch activity streams (second-by-second data)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "keys": stream_types,
                "key_by_type": "true",
            },
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()


async def get_athlete_zones(access_token: str) -> dict:
    """Fetch athlete heart rate zones from Strava."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete/zones",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_athlete(access_token: str) -> dict:
    """Fetch authenticated athlete profile."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

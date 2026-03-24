from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import strava_client, token_manager

router = APIRouter(prefix="/auth", tags=["auth"])

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"


@router.get("/strava")
async def strava_login():
    """Redirect user to Strava OAuth consent screen."""
    params = urlencode(
        {
            "client_id": settings.strava_client_id,
            "response_type": "code",
            "redirect_uri": f"{settings.base_url}/auth/callback",
            "scope": "read,activity:read_all,profile:read_all",
            "approval_prompt": "force",
        }
    )
    return RedirectResponse(f"{STRAVA_AUTH_URL}?{params}")


@router.get("/callback")
async def strava_callback(
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle Strava OAuth callback, exchange code for tokens."""
    data = await strava_client.exchange_token(code)

    athlete = data.get("athlete", {})
    athlete_name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()

    await token_manager.store_tokens(
        db,
        athlete_id=athlete.get("id", 0),
        athlete_name=athlete_name,
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
    )

    return RedirectResponse("/dashboard")


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """Check if we have valid Strava tokens."""
    token = await token_manager.get_tokens(db)
    if token:
        return {
            "authenticated": True,
            "athlete_id": token.athlete_id,
            "athlete_name": token.athlete_name,
        }
    return {"authenticated": False}


@router.get("/logout")
async def logout(db: AsyncSession = Depends(get_db)):
    """Clear stored tokens."""
    from sqlalchemy import delete

    from app.models import Token

    await db.execute(delete(Token))
    await db.commit()
    return RedirectResponse("/")

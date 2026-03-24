import base64
import hashlib
import time
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Token


def _get_fernet() -> Fernet:
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


async def store_tokens(
    db: AsyncSession,
    athlete_id: int,
    athlete_name: str,
    access_token: str,
    refresh_token: str,
    expires_at: int,
) -> None:
    result = await db.execute(select(Token).where(Token.id == 1))
    token = result.scalar_one_or_none()

    if token:
        token.athlete_id = athlete_id
        token.athlete_name = athlete_name
        token.access_token = encrypt(access_token)
        token.refresh_token = encrypt(refresh_token)
        token.expires_at = expires_at
    else:
        token = Token(
            id=1,
            athlete_id=athlete_id,
            athlete_name=athlete_name,
            access_token=encrypt(access_token),
            refresh_token=encrypt(refresh_token),
            expires_at=expires_at,
        )
        db.add(token)

    await db.commit()


async def get_tokens(db: AsyncSession) -> Optional[Token]:
    result = await db.execute(select(Token).where(Token.id == 1))
    return result.scalar_one_or_none()


async def get_valid_access_token(db: AsyncSession) -> Optional[str]:
    """Get a valid access token, refreshing if needed."""
    import httpx

    token = await get_tokens(db)
    if not token:
        return None

    # Refresh if expiring within 5 minutes
    if token.expires_at < time.time() + 300:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://www.strava.com/oauth/token",
                data={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": decrypt(token.refresh_token),
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            await store_tokens(
                db,
                athlete_id=token.athlete_id,
                athlete_name=token.athlete_name,
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
            )
            return data["access_token"]

    return decrypt(token.access_token)

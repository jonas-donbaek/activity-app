from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Shoe
from app.services import strava_client, token_manager


async def sync_shoes_from_strava(db: AsyncSession) -> int:
    """Sync all shoes from Strava athlete profile with actual total mileage."""
    access_token = await token_manager.get_valid_access_token(db)
    if not access_token:
        return 0

    athlete = await strava_client.get_athlete(access_token)
    strava_shoes = athlete.get("shoes", [])
    synced = 0

    for s in strava_shoes:
        gear_id = s["id"]
        result = await db.execute(
            select(Shoe).where(Shoe.strava_gear_id == gear_id)
        )
        shoe = result.scalar_one_or_none()

        if shoe:
            # Update existing shoe with Strava's total
            shoe.total_distance_m = s.get("distance", 0.0)
            shoe.name = s.get("name", shoe.name)
        else:
            # Create new shoe from Strava
            shoe = Shoe(
                name=s.get("name", "Unknown"),
                strava_gear_id=gear_id,
                total_distance_m=s.get("distance", 0.0),
            )
            db.add(shoe)
        synced += 1

    await db.commit()
    return synced


async def get_shoe_status(db: AsyncSession) -> List[dict]:
    """Get status of all active shoes."""
    result = await db.execute(select(Shoe).where(Shoe.active == True))
    shoes = result.scalars().all()

    statuses = []
    for shoe in shoes:
        km = shoe.total_distance_m / 1000
        warn_km = shoe.warn_distance_m / 1000
        retire_km = shoe.retire_distance_m / 1000

        if km >= retire_km:
            status = "retired"
            message = f"⛔ {shoe.name} har rundet {km:.0f} km - tid til nye sko!"
        elif km >= warn_km:
            status = "warning"
            remaining = retire_km - km
            message = (
                f"⚠️ {shoe.name} har {km:.0f} km - "
                f"kun {remaining:.0f} km til de bør udskiftes. "
                f"Overvej at begynde at køre de nye ind."
            )
        else:
            status = "ok"
            remaining = warn_km - km
            message = f"✅ {shoe.name}: {km:.0f} km ({remaining:.0f} km til advarsel)"

        statuses.append(
            {
                "id": shoe.id,
                "name": shoe.name,
                "total_km": round(km, 1),
                "warn_km": round(warn_km, 0),
                "retire_km": round(retire_km, 0),
                "status": status,
                "message": message,
                "pct_used": round(km / retire_km * 100, 1) if retire_km > 0 else 0,
            }
        )

    return statuses

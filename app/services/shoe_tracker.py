from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Shoe


async def update_shoe_mileage(db: AsyncSession, gear_id: str, distance_m: float) -> None:
    """Add distance to a shoe's total mileage."""
    if not gear_id:
        return

    result = await db.execute(select(Shoe).where(Shoe.strava_gear_id == gear_id))
    shoe = result.scalar_one_or_none()

    if shoe:
        shoe.total_distance_m += distance_m
        await db.commit()


async def get_shoe_status(db: AsyncSession) -> list[dict]:
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

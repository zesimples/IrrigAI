"""Regenerate and persist daily recommendations for every farm (or specific farms).

Same work the scheduler's daily job does (`generate_for_farm`, normally 05:00 UTC),
triggered on demand — e.g. to make the UI reflect new probe_calibration bounds
immediately instead of waiting for the next scheduled run.

Run inside the backend or worker container (needs PYTHONPATH=/app):

    python scripts/generate_recommendations.py                 # all farms
    python scripts/generate_recommendations.py <farm_id> ...   # specific farm ids

Per farm it prints how many recommendations were persisted. generate_for_farm
commits per sector and isolates per-sector failures, so one bad sector cannot
abort the farm.
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Farm
from app.services.recommendation_service import generate_for_farm


async def main() -> None:
    requested = [a for a in sys.argv[1:] if a.strip()]
    total = 0
    async with AsyncSessionLocal() as db:
        query = select(Farm)
        if requested:
            query = query.where(Farm.id.in_(requested))
        farms = (await db.execute(query)).scalars().all()
        if not farms:
            print("No matching farms found.")
            return
        for farm in farms:
            saved = await generate_for_farm(str(farm.id), db)
            total += len(saved)
            print(f"farm {farm.name} ({farm.id}): generated {len(saved)} recommendations")
    print(f"Done — {total} recommendations persisted across {len(farms)} farm(s).")


if __name__ == "__main__":
    asyncio.run(main())

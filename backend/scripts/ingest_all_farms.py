"""Run from inside the backend container:
    python scripts/ingest_all_farms.py [lookback_hours]

    lookback_hours defaults to 2 (normal scheduler run).
    Pass a larger value (e.g. 72) for initial backfill.
"""
import asyncio
import sys
from app.services.ingestion import ingest_farm
from app.database import AsyncSessionLocal
from sqlalchemy import text


async def main():
    lookback_hours = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id, name FROM farm"))
        farms = result.fetchall()
        if not farms:
            print("No farms found in DB.")
            return
        for farm_id, farm_name in farms:
            print(f"Ingesting {farm_name} (lookback={lookback_hours}h)...")
            summary = await ingest_farm(str(farm_id), db, lookback_hours=lookback_hours)
            print(summary)


asyncio.run(main())

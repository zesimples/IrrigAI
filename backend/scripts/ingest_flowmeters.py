"""Manually run flowmeter ingestion for all farms (same work as the
20-min scheduler job), without waiting for the next scheduled run.

Run from inside the backend container:
    python scripts/ingest_flowmeters.py

The service uses adaptive lookback (capped at 168h), so a single run will
also backfill any gap since each flowmeter's last stored reading.
"""
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Farm
from app.services.flowmeter_ingestion import FlowmeterIngestionService


async def main():
    service = FlowmeterIngestionService()
    async with AsyncSessionLocal() as db:
        farms = (await db.execute(select(Farm))).scalars().all()
        if not farms:
            print("No farms found in DB.")
            return
        for farm in farms:
            print(f"Ingesting flowmeters for {farm.name}...")
            summary = await service.ingest_farm(str(farm.id), db)
            print(summary)


asyncio.run(main())

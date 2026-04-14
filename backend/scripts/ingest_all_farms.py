"""Run from inside the backend container:
    python scripts/ingest_all_farms.py
"""
import asyncio
from app.services.ingestion import ingest_farm
from app.database import AsyncSessionLocal
from sqlalchemy import text


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id, name FROM farm"))
        farms = result.fetchall()
        if not farms:
            print("No farms found in DB.")
            return
        for farm_id, farm_name in farms:
            print(f"Ingesting {farm_name}...")
            summary = await ingest_farm(str(farm_id), db)
            print(summary)


asyncio.run(main())

"""Add missing ProbeDepth records for Conqueiros probes.

Run inside the backend container:
    python scripts/add_conqueiros_depths.py

Idempotent: inserts only depths that don't already exist.
After running, re-ingest with a 72h backfill to populate readings.
"""
import asyncio
import uuid

from sqlalchemy import select, text
from app.database import AsyncSessionLocal
from app.models import Probe, ProbeDepth

# Confirmed actual depths per probe external_id (from MyIrrigation API 2026-04-14)
PROBE_DEPTHS = {
    # Amendoal (project 959)
    "959/4914": [10, 20, 30, 40, 50, 60, 70, 80, 90],  # S02
    "959/4915": [5, 15, 25, 35, 45, 55, 65, 75, 85],   # S03
    "959/4912": [10, 20, 30, 40, 50, 60, 70, 80, 90],  # S12
    "959/8404": [10, 20, 30, 40, 50, 60],               # S19
    "959/7044": [10, 20, 30, 40, 50, 60],               # S25
    # Olival (project 1597)
    "1597/3634": [10, 20, 30, 40, 50, 60, 70, 80, 90], # O01A
    "1597/7674": [5, 15, 25, 35, 45, 55],              # O01B
    "1597/7673": [5, 15, 25, 35, 45, 55],              # O01C
    "1597/3891": [10, 20, 30, 40, 50, 60, 70, 80, 90], # O02
    "1597/3832": [10, 20, 30, 40, 50, 60, 70, 80, 90], # O05
}


async def main():
    async with AsyncSessionLocal() as db:
        total_added = 0

        for external_id, target_depths in PROBE_DEPTHS.items():
            # Look up probe
            result = await db.execute(
                select(Probe).where(Probe.external_id == external_id)
            )
            probe = result.scalar_one_or_none()
            if probe is None:
                print(f"  [SKIP] probe not found: {external_id}")
                continue

            # Get existing depths
            existing_result = await db.execute(
                select(ProbeDepth.depth_cm).where(ProbeDepth.probe_id == probe.id)
            )
            existing_depths = {row[0] for row in existing_result.fetchall()}

            # Insert missing ones
            added = 0
            for depth_cm in target_depths:
                if depth_cm not in existing_depths:
                    pd = ProbeDepth(
                        id=str(uuid.uuid4()),
                        probe_id=probe.id,
                        depth_cm=depth_cm,
                        sensor_type="soil_moisture",
                        calibration_offset=0.0,
                        calibration_factor=1.0,
                    )
                    db.add(pd)
                    added += 1

            total_added += added
            print(
                f"  {external_id}: existing={sorted(existing_depths)} "
                f"target={target_depths} added={added}"
            )

        await db.commit()
        print(f"\nDone. Added {total_added} ProbeDepth record(s).")
        print("Run a 72h backfill next:")
        print("  python scripts/ingest_all_farms.py 72")


asyncio.run(main())

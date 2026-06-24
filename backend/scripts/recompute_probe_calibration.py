"""Recompute probe-calibrated field-capacity bounds (probe_calibration table).

Calibrates each sector's FC/refill to its own VWC envelope so the water balance
stops pinning probe sectors at "100% da água disponível". Normally runs weekly via
the scheduler (`probe_calibration` job, Mon 04:00 UTC); this script triggers it
on demand — e.g. right after first deploy, before the first scheduled run.

Run inside the backend or worker container (needs PYTHONPATH=/app):

    python scripts/recompute_probe_calibration.py                 # all farms
    python scripts/recompute_probe_calibration.py <farm_id> ...   # specific farm ids

Per farm it prints how many sectors got a calibration row. Sectors without a probe
or with too little / implausible VWC history are skipped and keep their preset FC.
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Farm
from app.services.probe_calibration_service import ProbeCalibrationService


async def main() -> None:
    requested = [a for a in sys.argv[1:] if a.strip()]
    svc = ProbeCalibrationService()
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
            n = await svc.compute_all_for_farm(str(farm.id), db)
            await db.commit()
            total += n
            print(f"farm {farm.name} ({farm.id}): calibrated {n} sectors")
    print(f"Done — {total} sector calibration rows upserted across {len(farms)} farm(s).")


if __name__ == "__main__":
    asyncio.run(main())

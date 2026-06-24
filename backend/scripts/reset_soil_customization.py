"""Clear bulk/auto-set soil customization so probe calibration can drive FC.

Sectors had SectorCropProfile.is_customized=True with preset-derived FC/PWP that
were never a deliberate per-sector choice. While is_customized=True, that soil FC
overrides probe calibration (see engine/soil_bounds.resolve_soil_bounds), defeating
the calibration feature. This script, for every sector that HAS a probe_calibration
row, clears that bulk customization:

    is_customized = False
    field_capacity = NULL
    wilting_point  = NULL

After this, calibration drives FC for those sectors. A future *deliberate* soil-type
change in the UI re-writes field_capacity + is_customized=True and overrides
calibration again (the intended escape hatch). Clearing the FC (not just the flag)
prevents a later non-soil edit from resurrecting the stale value as an override.

Run inside the backend container (needs PYTHONPATH=/app):

    python scripts/reset_soil_customization.py            # apply to all calibrated sectors
    python scripts/reset_soil_customization.py --dry-run  # preview only, change nothing
    python scripts/reset_soil_customization.py <farm_id> ...   # limit to specific farms
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Plot, ProbeCalibration, Sector, SectorCropProfile


async def main() -> None:
    args = [a for a in sys.argv[1:] if a.strip()]
    dry_run = "--dry-run" in args
    farm_ids = [a for a in args if not a.startswith("--")]

    changed = 0
    async with AsyncSessionLocal() as db:
        # Sectors that have a calibration row (calibration can drive FC for these).
        q = (
            select(Sector, SectorCropProfile)
            .join(ProbeCalibration, ProbeCalibration.sector_id == Sector.id)
            .join(SectorCropProfile, SectorCropProfile.sector_id == Sector.id)
        )
        if farm_ids:
            q = q.join(Plot, Sector.plot_id == Plot.id).where(Plot.farm_id.in_(farm_ids))

        rows = (await db.execute(q)).all()
        for sector, scp in rows:
            if not (scp.is_customized or scp.field_capacity is not None
                    or scp.wilting_point is not None):
                continue  # already clean
            print(
                f"{'(dry-run) ' if dry_run else ''}reset {sector.name}: "
                f"is_customized {scp.is_customized}->False, "
                f"fc {scp.field_capacity}->None, wp {scp.wilting_point}->None"
            )
            if not dry_run:
                scp.is_customized = False
                scp.field_capacity = None
                scp.wilting_point = None
            changed += 1

        if not dry_run:
            await db.commit()

    verb = "would reset" if dry_run else "reset"
    print(f"Done — {verb} {changed} sector(s). "
          f"{'No changes written (dry-run).' if dry_run else 'Re-run generate_recommendations next.'}")


if __name__ == "__main__":
    asyncio.run(main())

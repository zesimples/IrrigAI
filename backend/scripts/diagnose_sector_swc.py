"""Read-only diagnostic: why does a sector's depletion disagree with the Soma chart?

Prints, for one sector: resolved soil bounds (source/CC/lower bound), effective
root depth, ProbeDepth rows vs depths actually reporting, latest VWC per depth,
the all-depth average vs the rootzone-weighted average, and the latest
recommendation snapshot (swc_current / taw / depletion / swc_source).

Usage (inside the backend container):
    python -m scripts.diagnose_sector_swc "Turno 3"
"""
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.engine.pipeline import resolve_effective_root_depth_m, resolve_sector_soil_bounds
from app.models import (
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Recommendation,
    Sector,
    SectorCropProfile,
)


async def main(name_fragment: str) -> None:
    # The dev engine is created with echo=True and caches the flag — silence all
    # INFO-and-below logging so the report is readable (print() is unaffected).
    logging.disable(logging.INFO)
    async with AsyncSessionLocal() as db:
        sector = (
            await db.execute(
                select(Sector).where(Sector.name.ilike(f"%{name_fragment}%")).limit(1)
            )
        ).scalar_one_or_none()
        if sector is None:
            print(f"No sector matching {name_fragment!r}")
            return
        plot = await db.get(Plot, sector.plot_id)
        print(f"Sector: {sector.name} ({sector.id})  crop={sector.crop_type}")

        bounds = await resolve_sector_soil_bounds(str(sector.id), db, plot=plot)
        print(f"Bounds: source={bounds.source}  CC={bounds.fc}  lower={bounds.pwp}")

        scp = (
            await db.execute(
                select(SectorCropProfile).where(SectorCropProfile.sector_id == sector.id)
            )
        ).scalar_one_or_none()
        tree_age = (
            datetime.now(UTC).year - sector.planting_year if sector.planting_year else None
        )
        root_m = resolve_effective_root_depth_m(scp, tree_age, sector.current_phenological_stage)
        print(f"Effective root depth: {root_m} m  (stage={sector.current_phenological_stage})")

        probes = (
            await db.execute(select(Probe).where(Probe.sector_id == sector.id))
        ).scalars().all()
        since = datetime.now(UTC) - timedelta(hours=48)
        for probe in probes:
            depths = (
                await db.execute(
                    select(ProbeDepth).where(ProbeDepth.probe_id == probe.id)
                )
            ).scalars().all()
            print(f"\nProbe {probe.external_id}: {len(depths)} ProbeDepth rows")
            latest_by_depth: dict[int, float] = {}
            for d in sorted(depths, key=lambda d: d.depth_cm):
                row = (
                    await db.execute(
                        select(ProbeReading)
                        .where(
                            ProbeReading.probe_depth_id == d.id,
                            ProbeReading.timestamp >= since,
                        )
                        .order_by(ProbeReading.timestamp.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                v = row.calibrated_value if row and row.calibrated_value is not None else (
                    row.raw_value if row else None
                )
                mark = "IN-ROOTZONE" if d.depth_cm <= root_m * 100 else ""
                v_txt = f"{v:.3f}" if v is not None else "—"
                print(f"  {d.depth_cm:>4}cm [{d.sensor_type}] latest48h={v_txt:>6}  {mark}")
                if v is not None:
                    latest_by_depth[d.depth_cm] = v
            if latest_by_depth:
                vals = list(latest_by_depth.values())
                in_zone = [v for dc, v in latest_by_depth.items() if dc <= root_m * 100]
                print(f"  live depths: {len(vals)}  all-depth avg: {sum(vals)/len(vals):.3f}")
                if in_zone:
                    print(f"  rootzone simple avg: {sum(in_zone)/len(in_zone):.3f}")

        rec = (
            await db.execute(
                select(Recommendation)
                .where(Recommendation.sector_id == sector.id)
                .order_by(Recommendation.generated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if rec and rec.inputs_snapshot:
            s = rec.inputs_snapshot
            print(
                f"\nLatest rec {rec.generated_at:%Y-%m-%d %H:%M}: action={rec.action}  "
                f"swc_current={s.get('swc_current')}  taw={s.get('taw_mm')}  "
                f"depletion={s.get('depletion_mm')}  swc_source={s.get('swc_source')}"
            )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))

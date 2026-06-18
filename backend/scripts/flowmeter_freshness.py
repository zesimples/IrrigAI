"""Compare each flowmeter's newest reading on the live MyIrrigation API vs what is
stored in the DB — answers "is stale flowmeter data our pipeline, or MyIrrigation's
own publishing lag?".

Run inside the worker or backend container (needs PYTHONPATH=/app):

    python scripts/flowmeter_freshness.py             # samples up to 5 data-having flowmeters
    python scripts/flowmeter_freshness.py 7003 6191   # specific external_device_ids

Prints, per device: DB latest reading vs the newest timestamp the API returns over
the last 48h, with a verdict. If db_latest == api_latest and both are old, the
ceiling is MyIrrigation (not us). If api_latest > db_latest, ingestion is behind.
"""
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.adapters.factory import get_probe_provider
from app.adapters.myirrigation import MyIrrigationAdapter, parse_flowmeter_data
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Farm, Flowmeter, Plot, Sector

_FMT = "%Y-%m-%d %H:%M:%S"


async def main() -> None:
    settings = get_settings()
    requested = [int(x) for x in sys.argv[1:] if x.strip().isdigit()]
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Flowmeter, Sector.name, Plot.farm_id)
                .join(Sector, Flowmeter.sector_id == Sector.id)
                .join(Plot, Sector.plot_id == Plot.id)
            )
        ).all()
        if requested:
            rows = [r for r in rows if r[0].external_device_id in requested]
        else:
            rows = sorted(
                [r for r in rows if r[0].last_reading_at is not None],
                key=lambda r: r[0].last_reading_at,
                reverse=True,
            )[:5]

        adapters: dict = {}

        async def adapter_for(farm_id):
            if farm_id not in adapters:
                farm = (
                    await db.execute(
                        select(Farm).where(Farm.id == farm_id).options(selectinload(Farm.credentials))
                    )
                ).scalar_one()
                adapters[farm_id] = get_probe_provider(settings, farm=farm)
            return adapters[farm_id]

        now = datetime.now(UTC)
        since = now - timedelta(hours=48)
        hdr = f"{'sector':<22}{'device':<8}{'db_latest':<28}{'api_latest':<28}verdict"
        print(hdr)
        print("-" * len(hdr))
        for fm, sector_name, farm_id in rows:
            ad = await adapter_for(farm_id)
            if not isinstance(ad, MyIrrigationAdapter):
                continue
            try:
                raw = await ad._post_form_json(
                    f"/data/devices/{fm.external_device_id}/data",
                    form_data={"start_date": since.strftime(_FMT), "end_date": now.strftime(_FMT)},
                    params={"use_key_index": ""},
                )
                api_latest = max((t for t, _ in parse_flowmeter_data(raw, fm.external_device_id)), default=None)
            except Exception as e:  # noqa: BLE001
                print(f"{sector_name:<22}{fm.external_device_id:<8}{str(fm.last_reading_at):<28}{"ERROR":<28}{type(e).__name__}: {str(e)[:60]}")
                continue
            db_latest = fm.last_reading_at
            if api_latest is None:
                verdict = "no API data in 48h"
            elif db_latest is None:
                verdict = "API has data, DB empty -> US"
            elif api_latest > db_latest:
                verdict = "API ahead -> ingest lag (US)"
            else:
                verdict = "DB == API -> source is the ceiling"
            print(f"{sector_name:<22}{fm.external_device_id:<8}{str(db_latest):<28}{str(api_latest):<28}{verdict}")
        print()
        print(f"now (UTC): {now.strftime(_FMT)}  — age = how far behind the API the freshest data is")


asyncio.run(main())

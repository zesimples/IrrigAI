"""Backfill flowmeter readings over a wider historical window.

Run from inside the backend container:
    python scripts/backfill_flowmeters.py --farm-name "Herdade dos Conqueiros" --days 30
    python scripts/backfill_flowmeters.py --farm-name "Herdade dos Conqueiros" --days 30 --device-id 7193

This uses farm-specific MyIrrigation credentials when present, inserts readings
idempotently, and runs irrigation-event detection for devices that returned data.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.adapters.factory import get_probe_provider
from app.adapters.myirrigation import MyIrrigationAdapter
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Farm, Flowmeter, Plot, Sector
from app.services.flowmeter_ingestion import FlowmeterIngestionService


async def _resolve_farm(db, farm_id: str | None, farm_name: str | None) -> Farm:
    stmt = select(Farm).options(selectinload(Farm.credentials))
    if farm_id:
        stmt = stmt.where(Farm.id == farm_id)
        label = f"id={farm_id}"
    elif farm_name:
        stmt = stmt.where(Farm.name.ilike(f"%{farm_name}%"))
        label = f"name~={farm_name}"
    else:
        raise ValueError("Pass --farm-id or --farm-name")

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        raise RuntimeError(f"No farm matched {label}")
    if len(rows) > 1:
        names = ", ".join(f"{farm.name} ({farm.id})" for farm in rows)
        raise RuntimeError(f"Multiple farms matched {label}: {names}")
    return rows[0]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm-id")
    parser.add_argument("--farm-name", default="Herdade dos Conqueiros")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--device-id",
        type=int,
        action="append",
        dest="device_ids",
        help="Limit to one external flowmeter device id; can be repeated",
    )
    args = parser.parse_args()

    if args.days <= 0:
        raise ValueError("--days must be greater than zero")

    since = datetime.now(UTC) - timedelta(days=args.days)
    until = datetime.now(UTC)
    service = FlowmeterIngestionService()

    async with AsyncSessionLocal() as db:
        try:
            farm = await _resolve_farm(db, args.farm_id, args.farm_name)
            adapter = get_probe_provider(get_settings(), farm=farm)
            if not isinstance(adapter, MyIrrigationAdapter):
                raise RuntimeError(f"Flowmeter backfill requires MyIrrigationAdapter, got {type(adapter)}")

            stmt = (
                select(Flowmeter)
                .join(Sector, Flowmeter.sector_id == Sector.id)
                .join(Plot, Sector.plot_id == Plot.id)
                .where(Plot.farm_id == farm.id, Flowmeter.is_active.is_(True))
                .order_by(Flowmeter.external_device_id)
            )
            if args.device_ids:
                stmt = stmt.where(Flowmeter.external_device_id.in_(args.device_ids))

            flowmeters = (await db.execute(stmt)).scalars().all()
            if not flowmeters:
                print(f"No active flowmeters found for farm {farm.name}")
                return

            print(
                f"Backfilling {len(flowmeters)} flowmeters for {farm.name} "
                f"window={since.isoformat()}..{until.isoformat()}"
            )

            total_inserted = 0
            total_events = 0
            devices_with_data = 0
            for flowmeter in flowmeters:
                inserted, earliest_ts, latest_ts = await service.ingest_device(
                    flowmeter, since, until, adapter, db
                )
                events = 0
                if earliest_ts is not None and latest_ts is not None:
                    devices_with_data += 1
                    events = await service._detect_and_store_events(
                        flowmeter, earliest_ts, latest_ts, db
                    )
                total_inserted += inserted
                total_events += events
                print(
                    f"device={flowmeter.external_device_id} "
                    f"inserted={inserted} events={events} "
                    f"range={earliest_ts.isoformat() if earliest_ts else '-'}.."
                    f"{latest_ts.isoformat() if latest_ts else '-'}"
                )

            await db.commit()
            print(
                f"DONE flowmeters={len(flowmeters)} devices_with_data={devices_with_data} "
                f"readings_inserted={total_inserted} events_detected={total_events}"
            )
        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())

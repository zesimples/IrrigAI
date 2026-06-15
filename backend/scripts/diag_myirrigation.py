"""Diagnose MyIrrigation per-device 406 "Client Signature Invalid".

Some flowmeter devices return 406 while probes + other flowmeters work with the
SAME credentials — pointing at a per-device key/signature (the `use_key_index`
query param, which the adapter currently always sends empty).

Run from inside the backend container (needs PYTHONPATH=/app):

  # 1) List all flowmeters with sector name, device id, last reading:
  python scripts/diag_myirrigation.py

  # 2) Probe a failing + working device by external_device_id, trying several
  #    use_key_index values (prints HTTP status + body for each):
  python scripts/diag_myirrigation.py 6191 7222 <working_device_id>
"""
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.adapters.factory import get_probe_provider
from app.adapters.myirrigation import MyIrrigationAdapter
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Farm, Flowmeter, Plot, Sector

_FMT = "%Y-%m-%d %H:%M:%S"
_KEY_INDEX_VALUES = ["", "1", "0", "true", "false"]


async def _adapter_for_farm(db, farm_id, settings):
    farm = (
        await db.execute(
            select(Farm).where(Farm.id == farm_id).options(selectinload(Farm.credentials))
        )
    ).scalar_one()
    return get_probe_provider(settings, farm=farm)


async def list_flowmeters(db):
    rows = (
        await db.execute(
            select(Flowmeter, Sector.name, Plot.farm_id)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .order_by(Sector.name)
        )
    ).all()
    print(f"{'sector':<22} {'device_id':<10} {'active':<7} last_reading_at")
    for fm, sector_name, _ in rows:
        print(f"{sector_name:<22} {str(fm.external_device_id):<10} {str(fm.is_active):<7} {fm.last_reading_at}")


async def probe_device(db, device_id, settings):
    fm = (
        await db.execute(select(Flowmeter).where(Flowmeter.external_device_id == device_id))
    ).scalar_one_or_none()
    if fm is None:
        print(f"device {device_id}: not found"); return
    sector = await db.get(Sector, fm.sector_id)
    plot = await db.get(Plot, sector.plot_id)
    adapter = await _adapter_for_farm(db, plot.farm_id, settings)
    if not isinstance(adapter, MyIrrigationAdapter):
        print(f"device {device_id}: not a MyIrrigation adapter"); return

    await adapter.authenticate()
    now = datetime.now(UTC)
    since = now - timedelta(days=2)
    body = {"start_date": since.strftime(_FMT), "end_date": now.strftime(_FMT)}

    print(f"\n=== device {device_id} (sector {sector.name}) ===")
    async with httpx.AsyncClient(timeout=30) as client:
        for ki in _KEY_INDEX_VALUES:
            try:
                resp = await client.post(
                    f"{adapter._base_url}/data/devices/{device_id}/data",
                    data=body,
                    params={"use_key_index": ki},
                    headers=adapter._auth_headers(),
                )
                print(f"  use_key_index={ki!r:<8} -> {resp.status_code}  {resp.text[:160]}")
            except Exception as e:  # noqa: BLE001
                print(f"  use_key_index={ki!r:<8} -> {type(e).__name__}: {str(e)[:120]}")


async def main():
    settings = get_settings()
    device_ids = [int(x) for x in sys.argv[1:] if x.strip().isdigit()]
    async with AsyncSessionLocal() as db:
        if not device_ids:
            await list_flowmeters(db)
            return
        for did in device_ids:
            await probe_device(db, did, settings)


asyncio.run(main())

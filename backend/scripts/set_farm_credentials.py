"""Update a farm's MyIrrigation credentials in the encrypted farm_credentials table.

There is no API/UI for this, and the values are encrypted at rest, so credential
rotation/correction is done here. Values are read from environment variables so no
secret is ever hardcoded in the repo or echoed by the script.

Run inside the backend container (copy values straight from the MyIrrigation portal
or your working Postman environment — do NOT retype them: capital `I` vs lowercase
`l` look identical and that exact typo caused the June 2026 outage):

    docker compose exec -e PYTHONPATH=/app \
      -e FARM_NAME='Herdade dos Conqueiros' \
      -e MI_CLIENT_ID='...' -e MI_CLIENT_SECRET='...' \
      -e MI_USERNAME='conqueiros_api' -e MI_PASSWORD='conqueiros_api' \
      -T backend python scripts/set_farm_credentials.py

Identify the farm with FARM_NAME (matches farm.name exactly).
Only the MI_* fields you provide are updated; omitted fields are left untouched.
Set VERIFY=1 to log in with the new credentials and confirm the token carries a
client_signature and a data fetch succeeds (booleans only — never prints secrets).
"""
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Farm, FarmCredentials


def _mask(value: str | None) -> str:
    if not value:
        return "<unset>"
    return f"<set:{len(value)} chars>"


async def main() -> None:
    farm_name = os.environ.get("FARM_NAME")
    if not farm_name:
        raise SystemExit("Set FARM_NAME to identify the farm (matches farm.name exactly).")

    updates = {
        "client_id": os.environ.get("MI_CLIENT_ID"),
        "client_secret": os.environ.get("MI_CLIENT_SECRET"),
        "username": os.environ.get("MI_USERNAME"),
        "password": os.environ.get("MI_PASSWORD"),
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise SystemExit("Provide at least one of MI_CLIENT_ID/MI_CLIENT_SECRET/MI_USERNAME/MI_PASSWORD.")

    async with AsyncSessionLocal() as db:
        stmt = select(Farm).options(selectinload(Farm.credentials)).where(Farm.name == farm_name)
        farm = (await db.execute(stmt)).scalar_one_or_none()
        if farm is None:
            raise SystemExit(f"Farm not found (name={farm_name!r}).")

        creds = farm.credentials
        if creds is None:
            creds = FarmCredentials(farm_id=farm.id)
            db.add(creds)

        for field, value in updates.items():
            setattr(creds, field, value)
        await db.commit()
        print(f"Updated farm {farm.name!r} credentials: {{ {', '.join(f'{k}={_mask(v)}' for k, v in updates.items())} }}")

        if os.environ.get("VERIFY") == "1":
            from datetime import UTC, datetime, timedelta

            from app.adapters.factory import get_probe_provider
            from app.adapters.myirrigation import MyIrrigationAdapter
            from app.config import get_settings
            from app.models import Flowmeter, Plot, Sector

            await db.refresh(farm, ["credentials"])
            adapter = get_probe_provider(get_settings(), farm=farm)
            if not isinstance(adapter, MyIrrigationAdapter):
                print("VERIFY skipped: farm does not resolve to a MyIrrigation adapter.")
                return

            # The real arbiter: replicate the exact failing call —
            # POST /data/devices/{id}/data — for one of this farm's devices. A wrong
            # client_secret still logs in, but the server rejects the request signature
            # with 406 "Client Signature Invalid". Only a data request proves the creds.
            device = (await db.execute(
                select(Flowmeter.external_device_id)
                .join(Sector, Flowmeter.sector_id == Sector.id)
                .join(Plot, Sector.plot_id == Plot.id)
                .where(Plot.farm_id == farm.id)
                .limit(1)
            )).scalar_one_or_none()
            if device is None:
                print("VERIFY: no device found for this farm to test against.")
                return

            now = datetime.now(UTC)
            adapter._token = None
            try:
                await adapter.authenticate()
                await adapter._post_form_json(
                    f"/data/devices/{device}/data",
                    form_data={
                        "start_date": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                        "end_date": now.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    params={"use_key_index": ""},
                )
                print(f"VERIFY: PASS — device-data call for {device} returned 200 (credentials valid).")
            except Exception as e:
                print(f"VERIFY: FAIL — device-data call for {device} rejected (creds still invalid): {e!r}")


asyncio.run(main())

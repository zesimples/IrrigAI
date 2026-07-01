"""Idempotent onboarding of the Innoliva client (6 polos, 77 olive sectors).

Reads docs/innoliva_device_mapping.csv and creates the entity tree, encrypted
per-farm credentials, and ProbeDepth rows (from each device's live sensor list).
Re-runnable: get-or-create by natural key. See
docs/superpowers/specs/2026-07-01-innoliva-onboarding-design.md.
"""
from __future__ import annotations

import asyncio
import copy
import csv
import os
import re
import uuid
from datetime import UTC, datetime, timedelta

# Polo → (MyIrrigation project_id, iMetos weather_device_id | None)
POLO_META: dict[str, tuple[str, str | None]] = {
    "Conceição": ("170", None),   # no iMetos → forecast-only
    "Covadonga": ("167", "574"),
    "Fátima": ("168", "590"),
    "Guadalupe": ("171", "571"),
    "Rocio": ("554", "573"),
    "Carmo": ("169", "572"),
}

_VARIETIES = ("Arbequina", "Cobrançosa", "Picoal")


def parse_variety(sector_name: str) -> str | None:
    """Return the olive variety named in the sector, else None."""
    for v in _VARIETIES:
        if v.lower() in sector_name.lower():
            return v
    return None


def extract_soil_moisture_depths(raw: dict) -> list[int]:
    """Sorted unique depths (cm) of exact 'Soil Moisture' sensors (not 'Summed')."""
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    sensors = data.get("sensors", []) if isinstance(data, dict) else []
    depths: set[int] = set()
    for s in sensors:
        if str(s.get("sensor_type", "")).strip().lower() != "soil moisture":
            continue
        m = re.search(r"(\d+)\s*cm", str(s.get("name", "")), re.IGNORECASE)
        if m:
            depths.add(int(m.group(1)))
    return sorted(depths)


# docs/ is NOT mounted into the container — the run steps copy the CSV to /app.
CSV_PATH = os.environ.get("INNOLIVA_CSV", "/app/innoliva_device_mapping.csv")


def _rows() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


async def main() -> None:
    from sqlalchemy import select

    from app.adapters.myirrigation import MyIrrigationAdapter
    from app.auth import hash_password
    from app.database import AsyncSessionLocal
    from app.models import (
        CropProfileTemplate,
        Farm,
        FarmCredentials,
        Plot,
        Probe,
        ProbeDepth,
        Sector,
        SectorCropProfile,
        User,
    )

    creds_env = {
        "username": os.environ["INNOLIVA_USERNAME"],
        "password": os.environ["INNOLIVA_PASSWORD"],
        "client_id": os.environ["INNOLIVA_CLIENT_ID"],
        "client_secret": os.environ["INNOLIVA_CLIENT_SECRET"],
    }
    owner_pw = os.environ["INNOLIVA_OWNER_PASSWORD"]

    adapter = MyIrrigationAdapter(
        base_url=os.environ.get("INNOLIVA_BASE_URL", "https://api.myirrigation.eu/api/v1"),
        **creds_env,
    )
    await adapter.authenticate()

    rows = _rows()
    async with AsyncSessionLocal() as session:
        # 1. Owner (get-or-create by email)
        owner = (
            await session.execute(select(User).where(User.email == "innoliva@irrigai.pt"))
        ).scalar_one_or_none()
        if owner is None:
            owner = User(
                id=str(uuid.uuid4()),
                email="innoliva@irrigai.pt",
                name="Innoliva",
                role="grower",
                language="pt",
                hashed_password=hash_password(owner_pw),
            )
            session.add(owner)
            await session.flush()

        # 2. Olive template (system default)
        olive_tmpl = (
            await session.execute(
                select(CropProfileTemplate).where(
                    CropProfileTemplate.crop_type == "olive",
                    CropProfileTemplate.is_system_default.is_(True),
                )
            )
        ).scalar_one()

        # 3. Per polo: Farm + FarmCredentials + Plot
        farms: dict[str, Farm] = {}
        plots: dict[str, Plot] = {}
        for polo, (project_id, weather_device_id) in POLO_META.items():
            farm_name = f"Polo de {polo}" if polo != "Carmo" else "Polo do Carmo"
            farm = (
                await session.execute(select(Farm).where(Farm.name == farm_name))
            ).scalar_one_or_none()
            if farm is None:
                farm = Farm(
                    id=str(uuid.uuid4()),
                    name=farm_name,
                    owner_id=owner.id,
                    region="Alentejo",
                    timezone="Europe/Lisbon",
                )
                session.add(farm)
                await session.flush()
                session.add(
                    FarmCredentials(
                        id=str(uuid.uuid4()),
                        farm_id=farm.id,
                        project_id=project_id,
                        weather_device_id=weather_device_id,
                        **creds_env,
                    )
                )
            farms[polo] = farm
            plot = (
                await session.execute(
                    select(Plot).where(Plot.farm_id == farm.id, Plot.name == "Olival")
                )
            ).scalar_one_or_none()
            if plot is None:
                plot = Plot(id=str(uuid.uuid4()), farm_id=farm.id, name="Olival")
                session.add(plot)
                await session.flush()
            plots[polo] = plot
        await session.flush()

        # 4. Per row: Sector + SectorCropProfile + Probe + ProbeDepths
        for r in rows:
            polo = r["polo"]
            plot = plots[polo]
            sector = (
                await session.execute(
                    select(Sector).where(
                        Sector.plot_id == plot.id, Sector.name == r["sector_name"]
                    )
                )
            ).scalar_one_or_none()
            if sector is None:
                sector = Sector(
                    id=str(uuid.uuid4()),
                    plot_id=plot.id,
                    name=r["sector_name"],
                    crop_type="olive",
                    variety=parse_variety(r["sector_name"]),
                )
                session.add(sector)
                await session.flush()
                session.add(
                    SectorCropProfile(
                        id=str(uuid.uuid4()),
                        sector_id=sector.id,
                        source_template_id=olive_tmpl.id,
                        crop_type="olive",
                        mad=olive_tmpl.mad,
                        root_depth_mature_m=olive_tmpl.root_depth_mature_m,
                        root_depth_young_m=olive_tmpl.root_depth_young_m,
                        maturity_age_years=olive_tmpl.maturity_age_years,
                        stages=copy.deepcopy(olive_tmpl.stages),
                        is_customized=False,
                    )
                )
            ext = r["external_id"]
            probe = (
                await session.execute(select(Probe).where(Probe.external_id == ext))
            ).scalar_one_or_none()
            if probe is None:
                probe = Probe(
                    id=str(uuid.uuid4()),
                    sector_id=sector.id,
                    external_id=ext,
                    serial_number=r["serial"],
                    manufacturer="Pessl Instruments",
                    model="TDT Soil Moisture",
                    health_status="ok",
                    is_reference=True,
                )
                session.add(probe)
                await session.flush()
                # ProbeDepths from live sensor discovery (short real window so
                # the device returns its sensor list).
                until = datetime.now(UTC)
                since = until - timedelta(hours=12)
                raw = await adapter._post_form_json(
                    f"/data/devices/{r['device_id']}/data",
                    form_data={
                        "start_date": since.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_date": until.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    params={"use_key_index": ""},
                )
                for depth_cm in extract_soil_moisture_depths(raw) or [30]:
                    session.add(
                        ProbeDepth(
                            id=str(uuid.uuid4()),
                            probe_id=probe.id,
                            depth_cm=depth_cm,
                            sensor_type="soil_moisture",
                            calibration_offset=0.0,
                            calibration_factor=1.0,
                        )
                    )
        await session.commit()
    print("Innoliva onboarding complete.")


if __name__ == "__main__":
    asyncio.run(main())

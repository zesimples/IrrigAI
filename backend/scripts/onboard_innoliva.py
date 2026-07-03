"""Idempotent onboarding of the Innoliva client (6 polos, 77 olive sectors).

Reads /app/innoliva_device_mapping.csv (copied in at run time via the
INNOLIVA_CSV env var or the run steps) and creates the entity tree, encrypted
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

        # 3. ONE Farm "Innoliva" (the client) + ONE FarmCredentials, then one
        #    Plot per polo — mirrors the ADL model (Herdade das Amendoas do Lago
        #    is one farm whose plots span several MyIrrigation projects). Probe
        #    reads are project-agnostic (they use device_id from external_id);
        #    the farm has a SINGLE weather source (project + iMetos device),
        #    chosen via env, exactly like ADL's single weather_device_id.
        weather_project_id = os.environ.get("INNOLIVA_WEATHER_PROJECT_ID") or None
        weather_device_id = os.environ.get("INNOLIVA_WEATHER_DEVICE_ID") or None
        if not weather_device_id:
            print(
                "[NOTICE] INNOLIVA_WEATHER_DEVICE_ID/PROJECT_ID not set — the Innoliva "
                "farm will have no dedicated weather station (forecast falls back to "
                "global/auto-detect). Set them to a representative polo's iMetos."
            )

        farm = (
            await session.execute(
                select(Farm).where(Farm.name == "Innoliva", Farm.owner_id == owner.id)
            )
        ).scalar_one_or_none()
        if farm is None:
            farm = Farm(
                id=str(uuid.uuid4()),
                name="Innoliva",
                owner_id=owner.id,
                # Representative Alentejo coordinate (from an Innoliva device location).
                # MyIrrigation weather is project-based so the exact value is not used for
                # weather; a non-null location is required to enable weather ingestion
                # (ingest_farm gates on farm.location_lat/lon) and for map display.
                location_lat=38.552,
                location_lon=-7.762,
                region="Alentejo",
                timezone="Europe/Lisbon",
            )
            session.add(farm)
            await session.flush()
            session.add(
                FarmCredentials(
                    id=str(uuid.uuid4()),
                    farm_id=farm.id,
                    project_id=weather_project_id,
                    weather_device_id=weather_device_id,
                    **creds_env,
                )
            )
            await session.flush()

        # One Plot per polo (CSV order). Plot name = the MyIrrigation project
        # name ("Polo de …" / "Polo do Carmo").
        plots: dict[str, Plot] = {}
        for r in rows:
            polo = r["polo"]
            if polo in plots:
                continue
            plot_name = f"Polo de {polo}" if polo != "Carmo" else "Polo do Carmo"
            plot = (
                await session.execute(
                    select(Plot).where(Plot.farm_id == farm.id, Plot.name == plot_name)
                )
            ).scalar_one_or_none()
            proj_id, wx_device_id = POLO_META[polo]
            if plot is None:
                plot = Plot(
                    id=str(uuid.uuid4()),
                    farm_id=farm.id,
                    name=plot_name,
                    myirrigation_project_id=proj_id,
                    weather_device_id=wx_device_id,
                )
                session.add(plot)
                await session.flush()
            else:
                # Backfill weather config on re-run — only fill when unset so we
                # don't clobber a value someone set manually.
                if plot.myirrigation_project_id is None:
                    plot.myirrigation_project_id = proj_id
                if plot.weather_device_id is None:
                    plot.weather_device_id = wx_device_id
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
            # ProbeDepths from live sensor discovery — runs for any probe that
            # has no depth rows yet (whether just created or from a prior partial
            # run).  On API error: skip this probe so a re-run retries discovery.
            existing = (
                await session.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe.id))
            ).scalars().first()
            if existing is None:
                until = datetime.now(UTC)
                since = until - timedelta(hours=12)
                try:
                    raw = await adapter._post_form_json(
                        f"/data/devices/{r['device_id']}/data",
                        form_data={
                            "start_date": since.strftime("%Y-%m-%d %H:%M:%S"),
                            "end_date": until.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        params={"use_key_index": ""},
                    )
                except Exception as exc:
                    print(f"[WARN] depth discovery failed for device {r['device_id']}: {exc}")
                    continue
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

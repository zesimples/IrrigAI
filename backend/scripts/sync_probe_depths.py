"""Discover and add missing ProbeDepth rows from MyIrrigation sensor metadata.

Run inside the backend container:
    python scripts/sync_probe_depths.py
    python scripts/sync_probe_depths.py --apply --backfill-hours 168

Default mode is a dry-run. The script only inserts missing depths; it never
deletes existing ProbeDepth rows.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.adapters.factory import get_probe_provider
from app.adapters.myirrigation import MyIrrigationAdapter, _normalise_unit
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Farm, Plot, Probe, ProbeDepth, Sector
from app.services.ingestion import ingest_farm

_SOIL_SENSOR_TYPES = {"suction", "soil moisture", "vwc", "watermark"}
_SOIL_UNITS = {"vwc_m3m3", "soil_tension_cbar"}


def _explicit_depth_cm(name: object) -> int | None:
    """Return depth only when the sensor name explicitly includes cm."""
    match = re.search(r"\b(\d{1,3})\s*cm\b", str(name or ""), re.IGNORECASE)
    if not match:
        return None
    depth = int(match.group(1))
    return depth if 0 < depth <= 300 else None


def _device_id(external_id: str) -> str:
    parts = external_id.split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"Invalid probe external_id {external_id!r}; expected project/device")
    return parts[1]


def _data_payload(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    return data if isinstance(data, dict) else raw


def _discover_depths(raw: object) -> tuple[list[int], list[str]]:
    """Extract explicit soil depths from a MyIrrigation device-data response."""
    data = _data_payload(raw)
    sensors = data.get("sensors") if isinstance(data, dict) else None
    values = data.get("values") if isinstance(data, dict) else None
    if not isinstance(sensors, list):
        return [], []
    if not isinstance(values, dict):
        values = {}

    discovered: set[int] = set()
    notes: list[str] = []

    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        sensor_type = str(sensor.get("sensor_type") or "").lower().strip()
        unit = _normalise_unit(str(sensor.get("units") or ""))
        if sensor_type not in _SOIL_SENSOR_TYPES and unit not in _SOIL_UNITS:
            continue

        depth = _explicit_depth_cm(sensor.get("name"))
        sensor_id = str(sensor.get("id") or "")
        value_count = len(values.get(sensor_id, {})) if isinstance(values.get(sensor_id), dict) else 0

        if depth is None:
            notes.append(
                f"ignored sensor without explicit cm: id={sensor_id} "
                f"name={sensor.get('name')!r} type={sensor.get('sensor_type')!r} unit={sensor.get('units')!r}"
            )
            continue

        discovered.add(depth)
        notes.append(
            f"depth={depth}cm sensor={sensor_id} values={value_count} "
            f"type={sensor.get('sensor_type')!r} unit={sensor.get('units')!r}"
        )

    return sorted(discovered), notes


async def _resolve_farms(db, farm_ids: list[str], farm_names: list[str]) -> list[Farm]:
    filters = []
    if farm_ids:
        filters.append(Farm.id.in_(farm_ids))
    for name in farm_names:
        filters.append(Farm.name.ilike(f"%{name}%"))

    stmt = select(Farm).options(selectinload(Farm.credentials))
    if filters:
        from sqlalchemy import or_

        stmt = stmt.where(or_(*filters))

    farms = (await db.execute(stmt.order_by(Farm.name))).scalars().all()
    seen: set[str] = set()
    unique: list[Farm] = []
    for farm in farms:
        if farm.id in seen:
            continue
        seen.add(farm.id)
        unique.append(farm)
    return unique


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm-id", action="append", default=[])
    parser.add_argument(
        "--farm-name",
        action="append",
        default=["Herdade dos Conqueiros", "Herdade das Amendoas do Lago"],
        help="Farm name substring. Repeatable. Defaults to Conqueiros and Amendoas do Lago.",
    )
    parser.add_argument("--days", type=int, default=7, help="Provider data window for sensor metadata.")
    parser.add_argument("--apply", action="store_true", help="Insert missing ProbeDepth rows.")
    parser.add_argument(
        "--backfill-hours",
        type=int,
        default=0,
        help="After applying, run probe/weather ingestion for each touched farm with this lookback.",
    )
    args = parser.parse_args()

    if args.days <= 0:
        raise ValueError("--days must be greater than zero")
    if args.backfill_hours < 0:
        raise ValueError("--backfill-hours cannot be negative")

    since = datetime.now(UTC) - timedelta(days=args.days)
    until = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        farms = await _resolve_farms(db, args.farm_id, args.farm_name)
        if not farms:
            raise RuntimeError("No farms matched the supplied filters.")

        total_added = 0
        touched_farm_ids: set[str] = set()

        for farm in farms:
            adapter = get_probe_provider(get_settings(), farm=farm)
            if not isinstance(adapter, MyIrrigationAdapter):
                print(f"[SKIP] {farm.name}: probe provider is {type(adapter).__name__}, not MyIrrigation")
                continue

            probes = (
                await db.execute(
                    select(Probe)
                    .join(Sector, Probe.sector_id == Sector.id)
                    .join(Plot, Sector.plot_id == Plot.id)
                    .where(Plot.farm_id == farm.id)
                    .order_by(Sector.name)
                )
            ).scalars().all()

            print(f"\nFarm: {farm.name} ({len(probes)} probes)")

            for probe in probes:
                try:
                    raw = await adapter._post_form_json(
                        f"/data/devices/{_device_id(probe.external_id)}/data",
                        form_data={
                            "start_date": since.strftime("%Y-%m-%d %H:%M:%S"),
                            "end_date": until.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        params={"use_key_index": ""},
                    )
                except Exception as exc:
                    print(f"  [ERR] {probe.external_id}: provider fetch failed: {exc}")
                    continue

                discovered, notes = _discover_depths(raw)
                existing = {
                    row[0]
                    for row in (
                        await db.execute(
                            select(ProbeDepth.depth_cm).where(
                                ProbeDepth.probe_id == probe.id,
                                ProbeDepth.sensor_type == "soil_moisture",
                            )
                        )
                    ).fetchall()
                }
                missing = [depth for depth in discovered if depth not in existing]

                print(
                    f"  {probe.external_id}: existing={sorted(existing)} "
                    f"discovered={discovered} missing={missing}"
                )
                for note in notes:
                    print(f"    - {note}")

                if args.apply and missing:
                    for depth_cm in missing:
                        db.add(
                            ProbeDepth(
                                id=str(uuid.uuid4()),
                                probe_id=probe.id,
                                depth_cm=depth_cm,
                                sensor_type="soil_moisture",
                                calibration_offset=0.0,
                                calibration_factor=1.0,
                            )
                        )
                    total_added += len(missing)
                    touched_farm_ids.add(str(farm.id))

        if args.apply:
            await db.commit()
            print(f"\nApplied. Added {total_added} ProbeDepth row(s).")
        else:
            await db.rollback()
            print("\nDry-run only. Re-run with --apply to insert missing depths.")

        if args.apply and args.backfill_hours and touched_farm_ids:
            print(f"\nBackfilling touched farms with lookback={args.backfill_hours}h...")
            for farm_id in sorted(touched_farm_ids):
                summary = await ingest_farm(farm_id, db, lookback_hours=args.backfill_hours)
                print(f"  {farm_id}: {summary}")


if __name__ == "__main__":
    asyncio.run(main())

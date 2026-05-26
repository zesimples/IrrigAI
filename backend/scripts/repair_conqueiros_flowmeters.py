"""Safely repair Herdade dos Conqueiros flowmeter metadata.

Run from inside the backend container:
    python scripts/repair_conqueiros_flowmeters.py
    python scripts/repair_conqueiros_flowmeters.py --apply

Default mode is dry-run. The script creates only missing flowmeter-only sectors
and missing flowmeter rows; it does not delete or recreate existing production
data.
"""
from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Farm, Flowmeter, Plot, Sector

FARM_NAME = "Herdade dos Conqueiros"
AMENDOAL_PLOT = "Amendoal Conqueiros"
OLIVAL_PLOT = "Olival"

FM_AMENDOAL: dict[int, tuple[int, str | None]] = {
    1: (6980, "E62300554"),
    2: (7036, "0020349A"),
    3: (7037, None),
    4: (6982, "E62300556"),
    5: (7005, "E62300579"),
    6: (6981, "E62300555"),
    7: (7006, "E62300580"),
    8: (6977, "E62300551"),
    9: (6979, "E62300553"),
    10: (7168, None),
    11: (7007, "E62300581"),
    12: (7169, "002034CE"),
    13: (7003, "E62300577"),
    14: (7001, "E62300575"),
    15: (6978, "E62300552"),
    16: (6983, "E62300557"),
    17: (7194, "E62300545"),
    18: (7222, "E62300982"),
    19: (7193, "E62300541"),
    20: (7191, "E62300543"),
    21: (7002, "E62300576"),
    22: (7004, "E62300578"),
    23: (7192, "E62300542"),
    24: (7008, "E62300582"),
    25: (7046, "031107A1"),
    26: (7195, "E62300544"),
}

FM_OLIVAL: dict[int, tuple[int, str | None]] = {
    1: (7034, "0120A035"),
    2: (6990, "E62300565"),
    3: (6989, "E62300563"),
    4: (6191, "E62000018"),
    5: (6995, "E62300570"),
    6: (6992, "E62300567"),
    7: (6984, "E62300558"),
    8: (7035, "002034C4"),
    9: (6997, "E62300572"),
    10: (6987, "E62300561"),
    11: (6994, "E62300569"),
    12: (7041, "0120A04A"),
    13: (7009, "E62300564"),
    14: (6988, "E62300562"),
    15: (7040, "0120A04E"),
    16: (6999, "E62300574"),
    17: (6986, "E62300560"),
    18: (6985, "E62300559"),
    19: (6998, "E62300573"),
    20: (7038, "203499"),
    21: (6996, "E62300571"),
    22: (6991, "E62300566"),
    23: (6993, "E62300568"),
}


@dataclass
class RepairStats:
    sectors_created: int = 0
    flowmeters_created: int = 0
    existing_flowmeters: int = 0
    skipped_conflicts: int = 0


def _sector_num(name: str) -> int | None:
    match = re.search(r"S0*(\d+)", name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _one(session: Session, stmt, label: str):
    rows = session.execute(stmt).scalars().all()
    if not rows:
        raise RuntimeError(f"{label} not found")
    if len(rows) > 1:
        raise RuntimeError(f"{label} matched {len(rows)} rows; make the selector stricter")
    return rows[0]


def _ensure_plot_flowmeters(
    session: Session,
    plot: Plot,
    crop_type: str,
    variety: str,
    sector_suffix: str,
    flowmeter_suffix: str,
    mapping: dict[int, tuple[int, str | None]],
    apply: bool,
) -> RepairStats:
    stats = RepairStats()
    sectors = session.execute(select(Sector).where(Sector.plot_id == plot.id)).scalars().all()
    by_num = {num: sector for sector in sectors if (num := _sector_num(sector.name)) is not None}

    for num in sorted(mapping):
        if num in by_num:
            continue

        sector = Sector(
            id=str(uuid.uuid4()),
            plot_id=plot.id,
            name=f"S{num:02d} {sector_suffix}",
            crop_type=crop_type,
            variety=variety,
            irrigation_strategy="full_etc",
            deficit_factor=1.0,
            rainfall_effectiveness=0.8,
        )
        by_num[num] = sector
        stats.sectors_created += 1
        print(f"PLAN create sector: {plot.name} / {sector.name}")
        if apply:
            session.add(sector)

    if apply:
        session.flush()

    farm_flowmeters = session.execute(
        select(Flowmeter)
        .join(Sector, Flowmeter.sector_id == Sector.id)
        .join(Plot, Sector.plot_id == Plot.id)
        .where(Plot.farm_id == plot.farm_id)
    ).scalars().all()
    existing_by_device = {flowmeter.external_device_id: flowmeter for flowmeter in farm_flowmeters}

    for num, (device_id, serial) in sorted(mapping.items()):
        sector = by_num.get(num)
        if sector is None:
            stats.skipped_conflicts += 1
            print(f"SKIP missing sector after repair planning: {plot.name} S{num:02d}")
            continue

        existing_for_sector = session.execute(
            select(Flowmeter).where(Flowmeter.sector_id == sector.id)
        ).scalar_one_or_none()
        if existing_for_sector is not None:
            stats.existing_flowmeters += 1
            if existing_for_sector.external_device_id != device_id:
                stats.skipped_conflicts += 1
                print(
                    "WARN existing sector flowmeter has different device: "
                    f"{sector.name} current={existing_for_sector.external_device_id} expected={device_id}"
                )
            continue

        duplicate = existing_by_device.get(device_id)
        if duplicate is not None and duplicate.sector_id != sector.id:
            stats.skipped_conflicts += 1
            print(
                "WARN device already assigned elsewhere; skipping duplicate: "
                f"device={device_id} target={sector.name}"
            )
            continue

        flowmeter = Flowmeter(
            id=str(uuid.uuid4()),
            sector_id=sector.id,
            external_device_id=device_id,
            serial_number=serial,
            name=f"Caudalímetro S{num:02d} {flowmeter_suffix}",
            is_active=True,
        )
        stats.flowmeters_created += 1
        print(f"PLAN create flowmeter: {sector.name} device={device_id} serial={serial or '-'}")
        if apply:
            session.add(flowmeter)
            existing_by_device[device_id] = flowmeter

    return stats


def _add_stats(left: RepairStats, right: RepairStats) -> RepairStats:
    return RepairStats(
        sectors_created=left.sectors_created + right.sectors_created,
        flowmeters_created=left.flowmeters_created + right.flowmeters_created,
        existing_flowmeters=left.existing_flowmeters + right.existing_flowmeters,
        skipped_conflicts=left.skipped_conflicts + right.skipped_conflicts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm-name", default=FARM_NAME)
    parser.add_argument("--apply", action="store_true", help="Commit the planned repair")
    args = parser.parse_args()

    engine = create_engine(get_settings().DATABASE_URL_SYNC)
    with Session(engine) as session:
        farm = _one(
            session,
            select(Farm).where(Farm.name == args.farm_name),
            f"Farm {args.farm_name!r}",
        )
        amendoal = _one(
            session,
            select(Plot).where(Plot.farm_id == farm.id, Plot.name == AMENDOAL_PLOT),
            f"Plot {AMENDOAL_PLOT!r}",
        )
        olival = _one(
            session,
            select(Plot).where(Plot.farm_id == farm.id, Plot.name == OLIVAL_PLOT),
            f"Plot {OLIVAL_PLOT!r}",
        )

        total = RepairStats()
        total = _add_stats(
            total,
            _ensure_plot_flowmeters(
                session,
                amendoal,
                crop_type="almond",
                variety="Amendoeira",
                sector_suffix="Amendoal",
                flowmeter_suffix="Amendoal",
                mapping=FM_AMENDOAL,
                apply=args.apply,
            ),
        )
        total = _add_stats(
            total,
            _ensure_plot_flowmeters(
                session,
                olival,
                crop_type="olive",
                variety="Oliveira",
                sector_suffix="Olival",
                flowmeter_suffix="Olival",
                mapping=FM_OLIVAL,
                apply=args.apply,
            ),
        )

        if args.apply:
            session.commit()
            mode = "APPLIED"
        else:
            session.rollback()
            mode = "DRY RUN"

    print(
        f"{mode}: sectors_created={total.sectors_created} "
        f"flowmeters_created={total.flowmeters_created} "
        f"existing_flowmeters={total.existing_flowmeters} "
        f"skipped_conflicts={total.skipped_conflicts}"
    )


if __name__ == "__main__":
    main()

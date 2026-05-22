# backend/app/api/v1/flowmeter.py
"""Flowmeter endpoints — sector-level readings/events and farm-level dashboard."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Farm, Flowmeter, FlowmeterReading, IrrigationEventDetected, Plot, Sector
from app.schemas.flowmeter import (
    CropSummary,
    FlowmeterDashboardResponse,
    FlowmeterEventsResponse,
    FlowmeterEventsSummary,
    FlowmeterOut,
    FlowmeterReadingPoint,
    FlowmeterReadingsResponse,
    FlowmeterSectorDashboard,
    IrrigationEventOut,
    SectorDailyBreakdown,
)

router = APIRouter(tags=["flowmeter"])


async def _get_flowmeter_or_404(sector_id: str, db: AsyncSession) -> Flowmeter:
    result = await db.execute(
        select(Flowmeter).where(Flowmeter.sector_id == sector_id, Flowmeter.is_active.is_(True))
    )
    flowmeter = result.scalar_one_or_none()
    if flowmeter is None:
        raise HTTPException(404, detail="No active flowmeter for this sector")
    return flowmeter


@router.get("/sectors/{sector_id}/flowmeter", response_model=FlowmeterOut)
async def get_sector_flowmeter(sector_id: str, db: AsyncSession = Depends(get_db)):
    return await _get_flowmeter_or_404(sector_id, db)


@router.get("/sectors/{sector_id}/flowmeter/readings", response_model=FlowmeterReadingsResponse)
async def get_flowmeter_readings(
    sector_id: str,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    interval: Literal["15m", "1h", "1d"] = Query("15m"),
    db: AsyncSession = Depends(get_db),
):
    flowmeter = await _get_flowmeter_or_404(sector_id, db)

    sector = await db.get(Sector, sector_id)
    now = datetime.now(UTC)
    since = since or (now - timedelta(days=7))
    until = until or now

    if interval == "15m":
        rows_result = await db.execute(
            select(FlowmeterReading)
            .where(
                FlowmeterReading.flowmeter_id == flowmeter.id,
                FlowmeterReading.timestamp >= since,
                FlowmeterReading.timestamp <= until,
            )
            .order_by(FlowmeterReading.timestamp)
        )
        readings = [
            FlowmeterReadingPoint(timestamp=r.timestamp, value=r.value_m3_ha)
            for r in rows_result.scalars().all()
        ]
    else:
        trunc = "hour" if interval == "1h" else "day"
        rows_result = await db.execute(
            select(
                sql_func.date_trunc(trunc, FlowmeterReading.timestamp).label("bucket"),
                sql_func.sum(FlowmeterReading.value_m3_ha).label("total"),
            )
            .where(
                FlowmeterReading.flowmeter_id == flowmeter.id,
                FlowmeterReading.timestamp >= since,
                FlowmeterReading.timestamp <= until,
            )
            .group_by("bucket")
            .order_by("bucket")
        )
        readings = [
            FlowmeterReadingPoint(timestamp=row.bucket, value=round(row.total or 0.0, 4))
            for row in rows_result.all()
        ]

    return FlowmeterReadingsResponse(
        flowmeter_id=flowmeter.id,
        sector_name=sector.name if sector else sector_id,
        crop=sector.crop_type if sector else "unknown",
        interval=interval,
        readings=readings,
    )


@router.get("/sectors/{sector_id}/flowmeter/events", response_model=FlowmeterEventsResponse)
async def get_flowmeter_events(
    sector_id: str,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    flowmeter = await _get_flowmeter_or_404(sector_id, db)

    now = datetime.now(UTC)
    since = since or (now - timedelta(days=7))
    until = until or now

    events_result = await db.execute(
        select(IrrigationEventDetected)
        .where(
            IrrigationEventDetected.flowmeter_id == flowmeter.id,
            IrrigationEventDetected.start_time >= since,
            IrrigationEventDetected.start_time <= until,
        )
        .order_by(IrrigationEventDetected.start_time.desc())
    )
    events = events_result.scalars().all()

    total_m3 = sum(e.total_m3_ha for e in events)
    period_days = max(1, (until - since).days)
    summary = FlowmeterEventsSummary(
        total_events=len(events),
        total_m3_ha=round(total_m3, 4),
        avg_m3_ha_per_event=round(total_m3 / len(events), 4) if events else 0.0,
        period_days=period_days,
    )
    return FlowmeterEventsResponse(
        events=[IrrigationEventOut.model_validate(e) for e in events],
        summary=summary,
    )


@router.get("/farms/{farm_id}/flowmeter-dashboard", response_model=FlowmeterDashboardResponse)
async def get_flowmeter_dashboard(
    farm_id: str,
    period: Literal["7d", "30d", "season"] = Query("7d"),
    db: AsyncSession = Depends(get_db),
):
    farm = await db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, detail="Farm not found")

    now = datetime.now(UTC)

    if period == "season":
        # Start = first flowmeter reading for this farm
        first_ts_result = await db.execute(
            select(sql_func.min(FlowmeterReading.timestamp))
            .join(Flowmeter, FlowmeterReading.flowmeter_id == Flowmeter.id)
            .join(Sector, Flowmeter.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .where(Plot.farm_id == farm_id)
        )
        first_ts = first_ts_result.scalar_one_or_none()
        since = first_ts or (now - timedelta(days=365))
    else:
        days = 7 if period == "7d" else 30
        since = now - timedelta(days=days)

    period_start = since.date()
    period_end = now.date()
    period_days = max(1, (period_end - period_start).days)

    # Load all flowmeters for this farm with sector info
    flowmeters_result = await db.execute(
        select(Flowmeter, Sector)
        .join(Sector, Flowmeter.sector_id == Sector.id)
        .join(Plot, Sector.plot_id == Plot.id)
        .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        .order_by(Sector.name)
    )
    flowmeter_sector_pairs = flowmeters_result.all()

    if not flowmeter_sector_pairs:
        raise HTTPException(404, detail="No flowmeters found for this farm")

    # Build daily totals per flowmeter
    daily_result = await db.execute(
        select(
            FlowmeterReading.flowmeter_id,
            sql_func.date_trunc("day", FlowmeterReading.timestamp).label("day"),
            sql_func.sum(FlowmeterReading.value_m3_ha).label("total"),
        )
        .where(
            FlowmeterReading.flowmeter_id.in_([fm.id for fm, _ in flowmeter_sector_pairs]),
            FlowmeterReading.timestamp >= since,
            FlowmeterReading.timestamp <= now,
        )
        .group_by(FlowmeterReading.flowmeter_id, "day")
    )
    # {flowmeter_id: {date: total}}
    daily_map: dict[str, dict[date, float]] = {}
    for row in daily_result.all():
        day_date = row.day.date() if hasattr(row.day, "date") else row.day
        daily_map.setdefault(row.flowmeter_id, {})[day_date] = round(row.total or 0.0, 4)

    # Latest event per flowmeter
    latest_events_result = await db.execute(
        select(IrrigationEventDetected)
        .where(
            IrrigationEventDetected.flowmeter_id.in_([fm.id for fm, _ in flowmeter_sector_pairs]),
            IrrigationEventDetected.start_time >= since,
        )
        .order_by(IrrigationEventDetected.start_time.desc())
    )
    all_events = latest_events_result.scalars().all()
    # {flowmeter_id: [events]}
    events_by_fm: dict[str, list[IrrigationEventDetected]] = {}
    for ev in all_events:
        events_by_fm.setdefault(ev.flowmeter_id, []).append(ev)

    # Build date range for daily_breakdown
    date_range = [
        (since + timedelta(days=i)).date()
        for i in range(period_days + 1)
        if (since + timedelta(days=i)).date() <= period_end
    ]

    sectors_out: list[FlowmeterSectorDashboard] = []
    farm_total = 0.0
    by_crop: dict[str, dict] = {}

    for flowmeter, sector in flowmeter_sector_pairs:
        fm_daily = daily_map.get(flowmeter.id, {})
        fm_events = events_by_fm.get(flowmeter.id, [])
        total = sum(fm_daily.values())
        last_event = fm_events[0] if fm_events else None
        crop = sector.crop_type

        farm_total += total
        crop_data = by_crop.setdefault(crop, {"total_m3_ha": 0.0, "num_sectors": 0, "num_events": 0})
        crop_data["total_m3_ha"] = round(crop_data["total_m3_ha"] + total, 4)
        crop_data["num_sectors"] += 1
        crop_data["num_events"] += len(fm_events)

        sectors_out.append(FlowmeterSectorDashboard(
            sector_id=sector.id,
            sector_name=sector.name,
            crop=crop,
            has_flowmeter=True,
            total_m3_ha=round(total, 4),
            num_events=len(fm_events),
            last_irrigation=last_event.start_time if last_event else None,
            last_event_m3_ha=last_event.total_m3_ha if last_event else None,
            daily_breakdown=[
                SectorDailyBreakdown(date=d, m3_ha=fm_daily.get(d, 0.0))
                for d in date_range
            ],
        ))

    return FlowmeterDashboardResponse(
        farm_name=farm.name,
        period=period,
        period_start=period_start,
        period_end=period_end,
        total_m3_ha=round(farm_total, 4),
        sectors=sectors_out,
        by_crop={k: CropSummary(**v) for k, v in by_crop.items()},
    )

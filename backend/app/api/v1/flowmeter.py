# backend/app/api/v1/flowmeter.py
"""Flowmeter endpoints — sector-level readings/events and farm-level dashboard."""
from __future__ import annotations

import json as _json
from dataclasses import asdict
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
    FlowmeterAnalysisRequest,
    FlowmeterAnalysisResponse,
    FlowmeterAnalysisStatistics,
    FlowmeterCropStats,
    FlowmeterDashboardResponse,
    FlowmeterDeviationsResponse,
    FlowmeterEventsResponse,
    FlowmeterEventsSummary,
    FlowmeterOut,
    FlowmeterReadingPoint,
    FlowmeterReadingsResponse,
    FlowmeterSectorAnalysisResponse,
    FlowmeterSectorDashboard,
    FlowmeterSectorStatistics,
    IrrigationEventOut,
    SectorDailyBreakdown,
)

router = APIRouter(tags=["flowmeter"])


def _build_farm_statistics(
    analytics: "FarmFlowmeterAnalytics",
) -> FlowmeterAnalysisStatistics:
    return FlowmeterAnalysisStatistics(
        total_m3_ha=analytics.total_m3_ha,
        total_events=analytics.total_events,
        sectors_with_data=analytics.total_sectors_with_data,
        sectors_without_data=analytics.total_sectors_without_data,
        by_crop={
            crop: FlowmeterCropStats(
                total_m3_ha=s.total_m3_ha,
                avg_per_sector=s.avg_m3_ha_per_sector,
                avg_per_event=s.avg_m3_ha_per_event,
                num_events=s.total_events,
            )
            for crop, s in analytics.by_crop.items()
        },
        stopped_sectors=[s.sector_name for s in analytics.stopped_sectors],
        top_consumers=[f"{r.sector_name} ({r.value:.1f} m³/ha)" for r in analytics.top_consumers],
        trend=analytics.trend,
        typical_start_hour=analytics.most_common_start_hour if analytics.start_hour_distribution else None,
    )


def _build_sector_statistics(
    sa: "SectorFlowmeterAnalytics",
) -> FlowmeterSectorStatistics:
    return FlowmeterSectorStatistics(
        total_m3_ha=sa.total_m3_ha,
        num_events=sa.num_events,
        avg_m3_ha_per_event=sa.avg_m3_ha_per_event,
        avg_interval_days=sa.avg_interval_days,
        pattern=sa.pattern,
        consistency_score=sa.consistency_score,
        vs_crop_avg_pct=sa.vs_crop_avg_pct,
        typical_start_hour=sa.typical_start_hour,
        avg_duration_minutes=sa.avg_duration_minutes,
    )


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

    # Ensure tz-aware for DB comparison
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

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

    # Ensure tz-aware for DB comparison
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

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
            .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
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

    # Build inclusive date range from period_start to period_end
    date_range = [
        period_start + timedelta(days=i)
        for i in range((period_end - period_start).days + 1)
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


@router.post(
    "/farms/{farm_id}/flowmeter-analysis",
    response_model=FlowmeterAnalysisResponse,
    tags=["flowmeter"],
)
async def farm_flowmeter_analysis(
    farm_id: str,
    body: FlowmeterAnalysisRequest = FlowmeterAnalysisRequest(),
    db: AsyncSession = Depends(get_db),
) -> FlowmeterAnalysisResponse:
    """On-demand AI analysis of farm irrigation consumption.

    Computes statistics from DB, calls the LLM, and caches the AI text for
    2 hours. Pass force_refresh=true to bypass the cache.
    """
    from app.ai.flowmeter_prompts import get_farm_analysis_prompt
    from app.ai.openai_client import get_chat_client
    from app.config import get_settings
    from app.services.flowmeter_analytics import FlowmeterAnalyticsService
    from app.services.flowmeter_cache import get_analysis_cache, set_analysis_cache

    settings = get_settings()

    # Always compute fresh statistics (fast DB queries)
    svc = FlowmeterAnalyticsService()
    try:
        analytics = await svc.compute_farm_analytics(
            farm_id=farm_id, period_days=body.period_days, db=db
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stats = _build_farm_statistics(analytics)

    # Check cache for AI text
    if not body.force_refresh:
        cached_text = await get_analysis_cache("farm", farm_id, body.period_days)
        if cached_text:
            return FlowmeterAnalysisResponse(analysis=cached_text, statistics=stats)

    # Build JSON context for LLM (exclude per-sector full details to keep prompt short;
    # rankings like top_consumers/lowest_consumers are kept — 5 items each, useful context)
    analytics_dict = asdict(analytics)
    analytics_dict.pop("sectors", None)  # 49 full SectorFlowmeterAnalytics — too verbose
    analytics_json = _json.dumps(analytics_dict, ensure_ascii=False, default=str, indent=2)

    prompt = get_farm_analysis_prompt(body.language).format(analytics_json=analytics_json)
    user_message = (
        f"Analisa o consumo de água da exploração nos últimos {body.period_days} dias."
        if body.language == "pt"
        else f"Analyze the farm's water consumption over the last {body.period_days} days."
    )

    client = get_chat_client(settings)
    try:
        analysis_text = await client.complete(prompt, user_message, max_tokens=800, temperature=0.3)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {exc}") from exc

    await set_analysis_cache("farm", farm_id, body.period_days, analysis_text)

    return FlowmeterAnalysisResponse(analysis=analysis_text, statistics=stats)


@router.post(
    "/sectors/{sector_id}/flowmeter-analysis",
    response_model=FlowmeterSectorAnalysisResponse,
    tags=["flowmeter"],
)
async def sector_flowmeter_analysis(
    sector_id: str,
    body: FlowmeterAnalysisRequest = FlowmeterAnalysisRequest(),
    db: AsyncSession = Depends(get_db),
) -> FlowmeterSectorAnalysisResponse:
    """On-demand AI analysis of a single sector's irrigation consumption."""
    from app.ai.flowmeter_prompts import get_sector_analysis_prompt
    from app.ai.openai_client import get_chat_client
    from app.config import get_settings
    from app.services.flowmeter_analytics import FlowmeterAnalyticsService
    from app.services.flowmeter_cache import get_analysis_cache, set_analysis_cache

    settings = get_settings()

    svc = FlowmeterAnalyticsService()
    try:
        sector_analytics = await svc.compute_sector_analytics(
            sector_id=sector_id, period_days=body.period_days, db=db
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stats = _build_sector_statistics(sector_analytics)

    if not body.force_refresh:
        cached_text = await get_analysis_cache("sector", sector_id, body.period_days)
        if cached_text:
            return FlowmeterSectorAnalysisResponse(analysis=cached_text, statistics=stats)

    analytics_json = _json.dumps(asdict(sector_analytics), ensure_ascii=False, default=str, indent=2)
    prompt = get_sector_analysis_prompt(body.language).format(analytics_json=analytics_json)
    user_message = (
        f"Analisa o consumo do setor '{sector_analytics.sector_name}' nos últimos {body.period_days} dias."
        if body.language == "pt"
        else f"Analyze sector '{sector_analytics.sector_name}' water consumption over the last {body.period_days} days."
    )

    client = get_chat_client(settings)
    try:
        analysis_text = await client.complete(prompt, user_message, max_tokens=600, temperature=0.3)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {exc}") from exc

    await set_analysis_cache("sector", sector_id, body.period_days, analysis_text)

    return FlowmeterSectorAnalysisResponse(analysis=analysis_text, statistics=stats)


@router.get("/farms/{farm_id}/flowmeter-deviations", response_model=FlowmeterDeviationsResponse)
async def get_flowmeter_deviations(
    farm_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return per-sector deviation summary vs crop interior-event averages (7-day window).

    Pure computation — no LLM, no cache, no DB writes. Used by the inline
    FlowmeterDeviationWarnings frontend component.
    """
    farm = await db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, detail="Farm not found")

    from app.alerts.flowmeter_checker import FlowmeterAlertChecker
    return await FlowmeterAlertChecker().compute_deviations(farm_id, db)

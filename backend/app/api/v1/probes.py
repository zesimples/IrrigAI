from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    IrrigationEvent,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    Sector,
    WeatherObservation,
)
from app.schemas.probe import (
    DepthReadings,
    ProbeDetectedEvent,
    ProbeCreate,
    ProbeDetail,
    ProbeDepthOut,
    ProbeOut,
    ProbeReadingsResponse,
    ProbeUpdate,
    ReferenceLines,
    TimeSeriesPoint,
)

router = APIRouter(tags=["probes"])


@router.get("/sectors/{sector_id}/probes", response_model=list[ProbeOut])
async def list_probes(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")
    probes = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalars().all()
    return [ProbeOut.model_validate(p) for p in probes]


@router.get("/probes/{probe_id}", response_model=ProbeDetail)
async def get_probe(probe_id: str, db: AsyncSession = Depends(get_db)):
    probe = await db.get(Probe, probe_id)
    if not probe:
        raise HTTPException(404, detail="Probe not found")
    depths = (
        await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe_id))
    ).scalars().all()
    return ProbeDetail(
        **ProbeOut.model_validate(probe).model_dump(),
        depths=[ProbeDepthOut.model_validate(d) for d in depths],
    )


@router.get("/probes/{probe_id}/readings", response_model=ProbeReadingsResponse)
async def get_probe_readings(
    probe_id: str,
    since: datetime | None = Query(None, description="ISO timestamp, defaults to 48h ago"),
    until: datetime | None = Query(None, description="ISO timestamp, defaults to now"),
    depth_cm: str | None = Query(None, description="Comma-separated depths, e.g. '10,30,60'"),
    interval: str | None = Query(None, description="Downsampling: '1h', '6h', '1d'"),
    db: AsyncSession = Depends(get_db),
):
    probe = await db.get(Probe, probe_id)
    if not probe:
        raise HTTPException(404, detail="Probe not found")

    # Time range defaults
    now = datetime.now(UTC)
    since = since or (now - timedelta(hours=48))
    until = until or now

    # Normalize tz
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

    # Depth filter
    depth_filter: set[int] | None = None
    if depth_cm:
        try:
            depth_filter = {int(d.strip()) for d in depth_cm.split(",") if d.strip()}
        except ValueError:
            raise HTTPException(400, detail="Invalid depth_cm format — use comma-separated integers")

    # Load depths
    depths_query = select(ProbeDepth).where(
        ProbeDepth.probe_id == probe_id,
        ProbeDepth.sensor_type == "soil_moisture",
    )
    if depth_filter:
        depths_query = depths_query.where(ProbeDepth.depth_cm.in_(depth_filter))
    depths = (await db.execute(depths_query)).scalars().all()

    # Downsampling step
    downsample_h = _parse_interval(interval)

    depth_results: list[DepthReadings] = []
    event_source_depths: list[DepthReadings] = []
    for depth in sorted(depths, key=lambda d: d.depth_cm):
        rows = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= since,
                    ProbeReading.timestamp <= until,
                    ProbeReading.unit == "vwc_m3m3",
                )
                .order_by(ProbeReading.timestamp)
            )
        ).scalars().all()

        points = [
            TimeSeriesPoint(
                timestamp=r.timestamp,
                vwc=r.calibrated_value if r.calibrated_value is not None else r.raw_value,
                quality=r.quality_flag,
            )
            for r in rows
        ]
        event_source_depths.append(DepthReadings(depth_cm=depth.depth_cm, readings=points))

        if downsample_h and points:
            points = _downsample(points, downsample_h)

        depth_results.append(DepthReadings(depth_cm=depth.depth_cm, readings=points))

    # Reference lines from the sector's plot
    sector = await db.get(Sector, probe.sector_id)
    plot = await db.get(Plot, sector.plot_id) if sector else None
    fc = plot.field_capacity if plot else None
    pwp = plot.wilting_point if plot else None
    optimal = [round(pwp + (fc - pwp) * 0.4, 3), round(pwp + (fc - pwp) * 0.8, 3)] if fc and pwp else None
    events = await _detect_wetting_events(
        db=db,
        sector=sector,
        plot=plot,
        depths=event_source_depths,
        since=since,
        until=until,
    )

    return ProbeReadingsResponse(
        probe_id=probe_id,
        depths=depth_results,
        reference_lines=ReferenceLines(
            field_capacity=fc,
            wilting_point=pwp,
            optimal_range=optimal,
        ),
        events=events,
    )


@router.post("/sectors/{sector_id}/probes", response_model=ProbeOut, status_code=201)
async def create_probe(sector_id: str, body: ProbeCreate, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")
    probe = Probe(sector_id=sector_id, **body.model_dump())
    db.add(probe)
    await db.commit()
    await db.refresh(probe)
    return ProbeOut.model_validate(probe)


@router.put("/probes/{probe_id}", response_model=ProbeOut)
async def update_probe(probe_id: str, body: ProbeUpdate, db: AsyncSession = Depends(get_db)):
    probe = await db.get(Probe, probe_id)
    if not probe:
        raise HTTPException(404, detail="Probe not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(probe, k, v)
    await db.commit()
    await db.refresh(probe)
    return ProbeOut.model_validate(probe)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_interval(interval: str | None) -> float | None:
    """Return interval in hours, or None for no downsampling."""
    if interval is None:
        return None
    mapping = {"1h": 1.0, "6h": 6.0, "12h": 12.0, "1d": 24.0}
    val = mapping.get(interval.lower())
    if val is None:
        raise HTTPException(400, detail=f"Invalid interval '{interval}'. Use: 1h, 6h, 12h, 1d")
    return val


def _downsample(points: list[TimeSeriesPoint], interval_h: float) -> list[TimeSeriesPoint]:
    """Bucket readings into interval-hour windows, keeping one per bucket (last value)."""
    if not points:
        return []
    result: list[TimeSeriesPoint] = []
    bucket_start = points[0].timestamp
    bucket_seconds = interval_h * 3600
    current_bucket: list[TimeSeriesPoint] = []

    for pt in points:
        elapsed = (pt.timestamp - bucket_start).total_seconds()
        if elapsed >= bucket_seconds and current_bucket:
            result.append(current_bucket[-1])
            bucket_start = pt.timestamp
            current_bucket = [pt]
        else:
            current_bucket.append(pt)

    if current_bucket:
        result.append(current_bucket[-1])

    return result


async def _detect_wetting_events(
    db: AsyncSession,
    sector: Sector | None,
    plot: Plot | None,
    depths: list[DepthReadings],
    since: datetime,
    until: datetime,
) -> list[ProbeDetectedEvent]:
    """Detect likely wetting fronts from VWC jumps and classify against known sources."""
    if not sector or not depths:
        return []

    candidates: list[dict[str, object]] = []
    for depth in depths:
        readings = sorted(
            (pt for pt in depth.readings if pt.quality != "invalid"),
            key=lambda pt: pt.timestamp,
        )
        previous: TimeSeriesPoint | None = None
        for point in readings:
            if previous is None:
                previous = point
                continue
            elapsed_h = (point.timestamp - previous.timestamp).total_seconds() / 3600
            delta = point.vwc - previous.vwc
            if 0 < elapsed_h <= 12 and delta >= 0.015:
                candidates.append(
                    {
                        "timestamp": point.timestamp,
                        "depth_cm": depth.depth_cm,
                        "delta_vwc": delta,
                    }
                )
            previous = point

    if not candidates:
        return []

    candidates.sort(key=lambda c: c["timestamp"])
    groups: list[list[dict[str, object]]] = []
    for candidate in candidates:
        if not groups:
            groups.append([candidate])
            continue
        last_ts = groups[-1][-1]["timestamp"]
        if isinstance(last_ts, datetime) and (candidate["timestamp"] - last_ts).total_seconds() <= 6 * 3600:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])

    window_start = since - timedelta(hours=24)
    window_end = until + timedelta(hours=24)
    irrigation_events = (
        await db.execute(
            select(IrrigationEvent)
            .where(
                IrrigationEvent.sector_id == sector.id,
                IrrigationEvent.start_time >= window_start,
                IrrigationEvent.start_time <= window_end,
            )
            .order_by(IrrigationEvent.start_time)
        )
    ).scalars().all()

    weather_events = []
    if plot:
        weather_events = (
            await db.execute(
                select(WeatherObservation)
                .where(
                    WeatherObservation.farm_id == plot.farm_id,
                    WeatherObservation.timestamp >= window_start,
                    WeatherObservation.timestamp <= window_end,
                    WeatherObservation.rainfall_mm.is_not(None),
                    WeatherObservation.rainfall_mm > 0.2,
                )
                .order_by(WeatherObservation.timestamp)
            )
        ).scalars().all()

    detected: list[ProbeDetectedEvent] = []
    for idx, group in enumerate(groups[:12]):
        timestamps = [c["timestamp"] for c in group if isinstance(c["timestamp"], datetime)]
        if not timestamps:
            continue
        event_ts = min(timestamps)
        depth_deltas: dict[int, float] = {}
        for candidate in group:
            depth_cm = candidate["depth_cm"]
            delta_vwc = candidate["delta_vwc"]
            if isinstance(depth_cm, int) and isinstance(delta_vwc, float):
                depth_deltas[depth_cm] = max(depth_deltas.get(depth_cm, 0), delta_vwc)

        depths_cm = sorted(depth_deltas)
        total_delta = round(sum(depth_deltas.values()), 4)
        irrigation = _nearest_irrigation(irrigation_events, event_ts)
        rain = _nearest_rain(weather_events, event_ts)
        kind = "unlogged"
        confidence = "medium" if len(depths_cm) >= 2 else "low"
        source_text = "sem registo de rega ou chuva próximo"
        irrigation_mm = None
        rainfall_mm = None

        if irrigation:
            kind = "irrigation"
            irrigation_mm = irrigation.applied_mm
            confidence = "high" if len(depths_cm) >= 2 else "medium"
            source_text = "compatível com rega registada"
        elif rain:
            kind = "rain"
            rainfall_mm = rain.rainfall_mm
            confidence = "high" if len(depths_cm) >= 2 else "medium"
            source_text = "compatível com chuva registada"

        detected.append(
            ProbeDetectedEvent(
                id=f"wetting-{idx}-{int(event_ts.timestamp())}",
                timestamp=event_ts,
                kind=kind,
                confidence=confidence,
                depths_cm=depths_cm,
                delta_vwc=total_delta,
                rainfall_mm=rainfall_mm,
                irrigation_mm=irrigation_mm,
                message=(
                    f"Aumento rápido de humidade em {len(depths_cm)} profundidade(s), "
                    f"{source_text}."
                ),
            )
        )

    return detected


def _nearest_irrigation(events: list[IrrigationEvent], timestamp: datetime) -> IrrigationEvent | None:
    nearby = [
        event
        for event in events
        if abs((event.start_time - timestamp).total_seconds()) <= 8 * 3600
    ]
    if not nearby:
        return None
    return min(nearby, key=lambda event: abs((event.start_time - timestamp).total_seconds()))


def _nearest_rain(events: list[WeatherObservation], timestamp: datetime) -> WeatherObservation | None:
    nearby = [
        event
        for event in events
        if abs((event.timestamp - timestamp).total_seconds()) <= 24 * 3600
    ]
    if not nearby:
        return None
    return max(nearby, key=lambda event: event.rainfall_mm or 0)

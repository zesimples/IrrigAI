from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.engine.water_event_detector import detect_water_events
from app.models import Plot, Probe, ProbeDepth, ProbeReading, Sector
from app.schemas.probe import (
    DepthReadings,
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
    events = await detect_water_events(
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

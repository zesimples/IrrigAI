import math
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.engine.water_event_detector import detect_water_events
from app.models import (
    DetectedWaterEvent,
    Plot,
    Probe,
    ProbeDepth,
    ProbeReading,
    ProviderIngestionRun,
    Sector,
)
from app.schemas.probe import (
    DepthReadings,
    DetectedWaterEventOut,
    IngestionRunOut,
    ProbeCreate,
    ProbeDepthDiagnostics,
    ProbeDepthOut,
    ProbeDetail,
    ProbeOut,
    ProbeReadingGap,
    ProbeReadingsDiagnosticsResponse,
    ProbeReadingsResponse,
    ProbeUpdate,
    ReferenceLines,
    TimeSeriesPoint,
    WaterEventConfirmBody,
)
from app.services.water_event_service import (
    detect_and_persist_water_events,
    list_persisted_water_events,
)

router = APIRouter(tags=["probes"])


@router.get("/sectors/{sector_id}/probes", response_model=list[ProbeOut])
async def list_probes(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    await access.sector(sector_id)
    probes = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalars().all()
    return [ProbeOut.model_validate(p) for p in probes]


@router.get("/probes/{probe_id}", response_model=ProbeDetail)
async def get_probe(probe_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    probe = await access.probe(probe_id)
    depths = (
        await db.execute(select(ProbeDepth).where(ProbeDepth.probe_id == probe_id))
    ).scalars().all()
    return ProbeDetail(
        **ProbeOut.model_validate(probe).model_dump(),
        depths=[ProbeDepthOut.model_validate(d) for d in depths],
    )


@router.get("/probes/{probe_id}/readings/diagnostics", response_model=ProbeReadingsDiagnosticsResponse)
async def get_probe_readings_diagnostics(
    probe_id: str,
    access: Access,
    since: datetime | None = Query(None, description="ISO timestamp, defaults to 7d ago"),
    until: datetime | None = Query(None, description="ISO timestamp, defaults to now"),
    db: AsyncSession = Depends(get_db),
):
    probe = await access.probe(probe_id)

    now = datetime.now(UTC)
    since = _ensure_utc(since or (now - timedelta(days=7)))
    until = _ensure_utc(until or now)
    if since >= until:
        raise HTTPException(400, detail="since must be before until")

    depths = (
        await db.execute(
            select(ProbeDepth)
            .where(ProbeDepth.probe_id == probe_id)
            .order_by(ProbeDepth.depth_cm)
        )
    ).scalars().all()

    depth_diagnostics: list[ProbeDepthDiagnostics] = []
    for depth in depths:
        rows = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id == depth.id,
                    ProbeReading.timestamp >= since,
                    ProbeReading.timestamp <= until,
                )
                .order_by(ProbeReading.timestamp)
            )
        ).scalars().all()
        depth_diagnostics.append(_build_depth_diagnostics(depth, rows, until))

    total_readings = sum(d.reading_count for d in depth_diagnostics)
    gap_count = sum(d.gap_count for d in depth_diagnostics)
    expected_intervals = [
        d.expected_interval_minutes
        for d in depth_diagnostics
        if d.expected_interval_minutes is not None
    ]
    max_gaps = [d.max_gap_minutes for d in depth_diagnostics if d.max_gap_minutes is not None]

    overall_status = _overall_diagnostics_status(depth_diagnostics)
    suggested_backfill_hours = _suggested_backfill_hours(depth_diagnostics)

    return ProbeReadingsDiagnosticsResponse(
        probe_id=probe_id,
        external_id=probe.external_id,
        since=since,
        until=until,
        probe_last_reading_at=probe.last_reading_at,
        depth_count=len(depths),
        total_readings=total_readings,
        overall_status=overall_status,
        expected_interval_minutes=round(statistics.median(expected_intervals), 1)
        if expected_intervals
        else None,
        max_gap_minutes=round(max(max_gaps), 1) if max_gaps else None,
        gap_count=gap_count,
        suggested_backfill_hours=suggested_backfill_hours,
        depths=depth_diagnostics,
    )


@router.get("/probes/{probe_id}/readings", response_model=ProbeReadingsResponse)
async def get_probe_readings(
    probe_id: str,
    access: Access,
    since: datetime | None = Query(None, description="ISO timestamp, defaults to 48h ago"),
    until: datetime | None = Query(None, description="ISO timestamp, defaults to now"),
    depth_cm: str | None = Query(None, description="Comma-separated depths, e.g. '10,30,60'"),
    interval: str | None = Query(None, description="Downsampling: '1h', '6h', '1d'"),
    db: AsyncSession = Depends(get_db),
):
    probe = await access.probe(probe_id)

    # Time range defaults
    now = datetime.now(UTC)
    since = since or (now - timedelta(hours=48))
    until = until or now

    # Normalize tz
    since = _ensure_utc(since)
    until = _ensure_utc(until)

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

    # Group by depth_cm to handle duplicate ProbeDepth records at the same depth
    from collections import defaultdict
    depths_by_cm: dict[int, list] = defaultdict(list)
    for d in depths:
        depths_by_cm[d.depth_cm].append(d)

    depth_results: list[DepthReadings] = []
    event_source_depths: list[DepthReadings] = []
    for depth_cm_val in sorted(depths_by_cm):
        depth_group = depths_by_cm[depth_cm_val]
        depth_ids = [d.id for d in depth_group]
        rows = (
            await db.execute(
                select(ProbeReading)
                .where(
                    ProbeReading.probe_depth_id.in_(depth_ids),
                    ProbeReading.timestamp >= since,
                    ProbeReading.timestamp <= until,
                    ProbeReading.unit == "vwc_m3m3",
                )
                .order_by(ProbeReading.timestamp)
            )
        ).scalars().all()

        # Deduplicate by timestamp (last write wins) when multiple depth records exist
        seen_ts: dict = {}
        for r in rows:
            seen_ts[r.timestamp] = r
        merged_rows = sorted(seen_ts.values(), key=lambda r: r.timestamp)

        points = [
            TimeSeriesPoint(
                timestamp=r.timestamp,
                vwc=r.calibrated_value if r.calibrated_value is not None else r.raw_value,
                quality=r.quality_flag,
            )
            for r in merged_rows
        ]
        event_source_depths.append(DepthReadings(depth_cm=depth_cm_val, readings=points))

        if downsample_h and points:
            points = _downsample(points, downsample_h)

        depth_results.append(DepthReadings(depth_cm=depth_cm_val, readings=points))

    # Reference lines must match the FC/refill the recommendation engine uses:
    # probe-calibrated envelope > SCP > plot/preset. Using only plot FC here made
    # the chart draw CC from the stale preset while the engine used calibration, so
    # a dry sector looked saturated. Share the engine's resolver.
    from app.engine.pipeline import resolve_effective_root_depth_m, resolve_sector_soil_bounds
    from app.engine.probe_interpreter import weighted_rootzone_series
    from app.models import SectorCropProfile

    sector = await db.get(Sector, probe.sector_id)
    plot = await db.get(Plot, sector.plot_id) if sector else None
    if sector is not None:
        bounds = await resolve_sector_soil_bounds(str(sector.id), db, plot=plot)
        fc = bounds.fc
        pwp = bounds.pwp
    else:
        fc = pwp = None
    optimal = [round(pwp + (fc - pwp) * 0.4, 3), round(pwp + (fc - pwp) * 0.8, 3)] if fc and pwp else None

    # Rootzone-weighted SWC overlay: the same weighted average the recommendation
    # engine uses (build_sector_context + probe_interpreter._compute_rootzone), so
    # the chart's "Profundidades" view can visually agree with the recommendation
    # even on split-moisture profiles where the Soma view looks misleadingly green.
    root_depth_cm: float | None = None
    rootzone_points: list[TimeSeriesPoint] = []
    if sector is not None:
        scp = (
            await db.execute(
                select(SectorCropProfile).where(SectorCropProfile.sector_id == sector.id)
            )
        ).scalar_one_or_none()
        tree_age = (
            datetime.now(UTC).year - sector.planting_year
            if sector.planting_year is not None
            else None
        )
        root_depth_m = resolve_effective_root_depth_m(
            scp, tree_age, sector.current_phenological_stage
        )
        root_depth_cm = root_depth_m * 100
        # Weight from the SAME (already-downsampled) points sent to the chart, so the
        # rootzone line's timestamps are a subset of the depth lines' timestamps and
        # the two can't drift out of phase under any interval (independent downsampling
        # of two series bucketed from different first-timestamps would misalign them).
        series_by_depth: dict[int, list[tuple]] = {
            dr.depth_cm: [(p.timestamp, p.vwc) for p in dr.readings] for dr in depth_results
        }
        rootzone_series = weighted_rootzone_series(series_by_depth, root_depth_cm)
        rootzone_points = [
            TimeSeriesPoint(timestamp=ts, vwc=vwc, quality="ok") for ts, vwc in rootzone_series
        ]

    # Read-only: event persistence happens after ingestion or via explicit refresh.
    persisted = await list_persisted_water_events(
        probe_id=probe_id, db=db, since=since, until=until, limit=200
    )
    events = [_persisted_to_event_schema(e) for e in persisted]
    # Sort newest-last to match historic in-memory ordering by timestamp.
    events.sort(key=lambda e: e.timestamp)

    # Fallback: if we have no persisted events at all but the engine would still
    # produce inline events (e.g. seeded but never persisted), surface those.
    if not events:
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
        rootzone_swc=rootzone_points,
        root_depth_cm=root_depth_cm,
    )


@router.post("/sectors/{sector_id}/probes", response_model=ProbeOut, status_code=201)
async def create_probe(
    sector_id: str,
    body: ProbeCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
    probe = Probe(sector_id=sector_id, **body.model_dump())
    db.add(probe)
    await db.commit()
    await db.refresh(probe)
    return ProbeOut.model_validate(probe)


@router.put("/probes/{probe_id}", response_model=ProbeOut)
async def update_probe(
    probe_id: str,
    body: ProbeUpdate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    probe = await access.probe(probe_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(probe, k, v)
    await db.commit()
    await db.refresh(probe)
    return ProbeOut.model_validate(probe)


# ---------------------------------------------------------------------------
# Ingestion runs
# ---------------------------------------------------------------------------

@router.get("/probes/{probe_id}/ingestion-runs", response_model=list[IngestionRunOut])
async def list_probe_ingestion_runs(
    probe_id: str,
    access: Access,
    limit: int = Query(20, ge=1, le=100),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent ProviderIngestionRun rows for a probe."""
    await access.probe(probe_id)

    stmt = (
        select(ProviderIngestionRun)
        .where(ProviderIngestionRun.probe_id == probe_id)
        .order_by(ProviderIngestionRun.started_at.desc())
        .limit(limit)
    )
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        stmt = stmt.where(ProviderIngestionRun.started_at >= since)
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        stmt = stmt.where(ProviderIngestionRun.started_at <= until)

    rows = (await db.execute(stmt)).scalars().all()
    return [IngestionRunOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Persisted water events
# ---------------------------------------------------------------------------

@router.get("/probes/{probe_id}/water-events", response_model=list[DetectedWaterEventOut])
async def list_probe_water_events(
    probe_id: str,
    access: Access,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return persisted DetectedWaterEvent rows for a probe."""
    await access.probe(probe_id)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    rows = await list_persisted_water_events(probe_id, db, since=since, until=until, limit=limit)
    return [DetectedWaterEventOut.model_validate(r) for r in rows]


@router.post("/probes/{probe_id}/water-events/refresh", response_model=list[DetectedWaterEventOut])
async def refresh_probe_water_events(
    probe_id: str,
    access: Access,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly run detection and persist water events for a probe."""
    await access.probe(probe_id)
    if since is not None:
        since = _ensure_utc(since)
    if until is not None:
        until = _ensure_utc(until)

    rows = await detect_and_persist_water_events(
        probe_id=probe_id,
        db=db,
        since=since,
        until=until,
    )
    await db.commit()
    return [DetectedWaterEventOut.model_validate(r) for r in rows]


@router.post("/water-events/{event_id}/confirm", response_model=DetectedWaterEventOut)
async def confirm_water_event(
    event_id: str,
    access: Access,
    body: WaterEventConfirmBody = WaterEventConfirmBody(),
    db: AsyncSession = Depends(get_db),
):
    event = await access.water_event(event_id)
    event.status = "confirmed"
    event.confirmed_at = datetime.now(UTC)
    if body.notes:
        event.notes = body.notes
    if body.kind:
        event.kind = body.kind
    await db.commit()
    await db.refresh(event)
    return DetectedWaterEventOut.model_validate(event)


@router.post("/water-events/{event_id}/reject", response_model=DetectedWaterEventOut)
async def reject_water_event(
    event_id: str,
    access: Access,
    body: WaterEventConfirmBody = WaterEventConfirmBody(),
    db: AsyncSession = Depends(get_db),
):
    event = await access.water_event(event_id)
    event.status = "rejected"
    event.confirmed_at = datetime.now(UTC)
    if body.notes:
        event.notes = body.notes
    await db.commit()
    await db.refresh(event)
    return DetectedWaterEventOut.model_validate(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def _build_depth_diagnostics(
    depth: ProbeDepth,
    rows: list[ProbeReading],
    until: datetime,
) -> ProbeDepthDiagnostics:
    if not rows:
        return ProbeDepthDiagnostics(
            depth_cm=depth.depth_cm,
            sensor_type=depth.sensor_type,
            reading_count=0,
            gap_count=0,
            status="no_data",
            notes=["No stored readings for this depth in the selected window."],
        )

    timestamps = [_ensure_utc(row.timestamp) for row in rows]
    deltas_min = [
        (timestamps[idx] - timestamps[idx - 1]).total_seconds() / 60
        for idx in range(1, len(timestamps))
        if timestamps[idx] > timestamps[idx - 1]
    ]
    median_interval = statistics.median(deltas_min) if deltas_min else None
    expected_interval = _expected_interval_minutes(deltas_min)
    gap_threshold = expected_interval * 1.75 if expected_interval else None
    gaps = _reading_gaps(timestamps, expected_interval, gap_threshold)
    max_gap = max(deltas_min) if deltas_min else None
    freshness_hours = (until - timestamps[-1]).total_seconds() / 3600
    coverage = _coverage_pct(timestamps, expected_interval)
    quality_counts = Counter(row.quality_flag for row in rows)
    unit = Counter(row.unit for row in rows).most_common(1)[0][0]
    notes = _diagnostic_notes(
        rows=rows,
        gaps=gaps,
        coverage_pct=coverage,
        freshness_hours=freshness_hours,
        expected_interval=expected_interval,
    )
    status = _depth_status(
        gaps=gaps,
        coverage_pct=coverage,
        freshness_hours=freshness_hours,
        expected_interval=expected_interval,
    )

    return ProbeDepthDiagnostics(
        depth_cm=depth.depth_cm,
        sensor_type=depth.sensor_type,
        unit=unit,
        reading_count=len(rows),
        first_reading_at=timestamps[0],
        last_reading_at=timestamps[-1],
        latest_quality=rows[-1].quality_flag,
        quality_counts=dict(quality_counts),
        median_interval_minutes=round(median_interval, 1) if median_interval else None,
        expected_interval_minutes=round(expected_interval, 1) if expected_interval else None,
        max_gap_minutes=round(max_gap, 1) if max_gap else None,
        gap_threshold_minutes=round(gap_threshold, 1) if gap_threshold else None,
        gap_count=len(gaps),
        gaps=gaps[:20],
        coverage_pct=round(coverage, 1) if coverage is not None else None,
        freshness_hours=round(freshness_hours, 2),
        status=status,
        notes=notes,
    )


def _expected_interval_minutes(deltas_min: list[float]) -> float | None:
    if not deltas_min:
        return None
    rounded = [max(1, int(round(delta / 15) * 15)) for delta in deltas_min if delta > 0]
    if not rounded:
        return None
    counts = Counter(rounded)
    mode, mode_count = counts.most_common(1)[0]
    if mode_count >= max(2, len(rounded) * 0.25):
        return float(mode)
    return float(statistics.median(rounded))


def _reading_gaps(
    timestamps: list[datetime],
    expected_interval: float | None,
    gap_threshold: float | None,
) -> list[ProbeReadingGap]:
    if expected_interval is None or gap_threshold is None:
        return []

    gaps: list[ProbeReadingGap] = []
    for idx in range(1, len(timestamps)):
        duration_min = (timestamps[idx] - timestamps[idx - 1]).total_seconds() / 60
        if duration_min > gap_threshold:
            expected_missing = max(1, int(round(duration_min / expected_interval)) - 1)
            gaps.append(
                ProbeReadingGap(
                    start=timestamps[idx - 1],
                    end=timestamps[idx],
                    duration_minutes=round(duration_min, 1),
                    expected_missing_readings=expected_missing,
                )
            )
    return gaps


def _coverage_pct(
    timestamps: list[datetime],
    expected_interval: float | None,
) -> float | None:
    if expected_interval is None or len(timestamps) < 2:
        return None
    span_min = (timestamps[-1] - timestamps[0]).total_seconds() / 60
    if span_min <= 0:
        return None
    expected_count = math.floor(span_min / expected_interval) + 1
    if expected_count <= 0:
        return None
    return min(100.0, len(timestamps) / expected_count * 100)


def _depth_status(
    gaps: list[ProbeReadingGap],
    coverage_pct: float | None,
    freshness_hours: float,
    expected_interval: float | None,
) -> str:
    stale_threshold_h = 6.0
    if expected_interval is not None:
        stale_threshold_h = max(6.0, expected_interval / 60 * 2.5)
    if freshness_hours > stale_threshold_h:
        return "stale"
    if gaps or (coverage_pct is not None and coverage_pct < 90):
        return "partial"
    return "ok"


def _diagnostic_notes(
    rows: list[ProbeReading],
    gaps: list[ProbeReadingGap],
    coverage_pct: float | None,
    freshness_hours: float,
    expected_interval: float | None,
) -> list[str]:
    notes: list[str] = []
    if expected_interval is not None:
        notes.append(f"Estimated provider cadence is about {expected_interval:.0f} minutes.")
    if gaps:
        longest = max(gaps, key=lambda gap: gap.duration_minutes)
        notes.append(
            f"Detected {len(gaps)} storage gap(s); longest gap is {longest.duration_minutes:.0f} minutes."
        )
    if coverage_pct is not None and coverage_pct < 90:
        notes.append(f"Coverage is {coverage_pct:.0f}% versus expected cadence.")
    if freshness_hours > 6:
        notes.append(f"Latest stored reading is {freshness_hours:.1f} hours before the query end.")
    invalid_or_suspect = sum(1 for row in rows if row.quality_flag != "ok")
    if invalid_or_suspect:
        notes.append(f"{invalid_or_suspect} reading(s) are marked suspect or invalid.")
    if not notes:
        notes.append("Stored readings are continuous for the estimated cadence.")
    return notes


def _overall_diagnostics_status(depths: list[ProbeDepthDiagnostics]) -> str:
    if not depths or all(depth.status == "no_data" for depth in depths):
        return "no_data"
    if any(depth.status == "stale" for depth in depths):
        return "stale"
    if any(depth.status in {"partial", "no_data"} for depth in depths):
        return "partial"
    return "ok"


def _suggested_backfill_hours(depths: list[ProbeDepthDiagnostics]) -> int:
    max_gap_h = 0.0
    for depth in depths:
        for gap in depth.gaps:
            max_gap_h = max(max_gap_h, gap.duration_minutes / 60)
        if depth.freshness_hours is not None:
            max_gap_h = max(max_gap_h, depth.freshness_hours)
    if max_gap_h <= 0:
        return 24
    return min(168, max(24, math.ceil(max_gap_h + 6)))


def _persisted_to_event_schema(event: "DetectedWaterEvent"):
    """Convert a persisted DetectedWaterEvent to the wire-format ProbeDetectedEvent."""
    from app.schemas.probe import ProbeDetectedEvent

    return ProbeDetectedEvent(
        id=event.id,
        timestamp=event.timestamp,
        kind=event.kind,  # type: ignore[arg-type]
        confidence=event.confidence,  # type: ignore[arg-type]
        status=event.status,  # type: ignore[arg-type]
        depths_cm=list(event.depths_cm or []),
        delta_vwc=event.delta_vwc,
        rainfall_mm=event.rainfall_mm,
        irrigation_mm=event.irrigation_mm,
        score=event.score,
        probability_irrigation=event.probability_irrigation,
        probability_rain=event.probability_rain,
        probability_unlogged=event.probability_unlogged,
        source_match_score=event.source_match_score,
        depth_sequence_score=event.depth_sequence_score,
        signal_strength_score=event.signal_strength_score,
        sensor_quality_score=event.sensor_quality_score,
        message=event.message,
    )

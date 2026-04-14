from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Alert, IrrigationEvent, IrrigationSystem, Plot, Probe, Recommendation, Sector
from app.schemas.common import PaginatedResponse
from app.schemas.sector import (
    IrrigationSystemCreate,
    IrrigationSystemOut,
    ProbeHealthSummary,
    SectorCreate,
    SectorDetail,
    SectorOut,
    SectorStatus,
    SectorUpdate,
)

router = APIRouter(tags=["sectors"])


@router.get("/plots/{plot_id}/sectors", response_model=PaginatedResponse[SectorOut])
async def list_sectors(
    plot_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    plot = await db.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, detail="Plot not found")

    offset = (page - 1) * page_size
    total = (
        await db.execute(
            select(func.count()).select_from(Sector).where(Sector.plot_id == plot_id)
        )
    ).scalar_one()
    sectors = (
        await db.execute(
            select(Sector).where(Sector.plot_id == plot_id).offset(offset).limit(page_size)
        )
    ).scalars().all()
    return PaginatedResponse(
        items=[SectorOut.model_validate(s) for s in sectors],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sectors/{sector_id}", response_model=SectorDetail)
async def get_sector(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    irrig_result = await db.execute(
        select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id)
    )
    irrig = irrig_result.scalar_one_or_none()
    probe_count = (
        await db.execute(
            select(func.count()).select_from(Probe).where(Probe.sector_id == sector_id)
        )
    ).scalar_one()

    return SectorDetail(
        **SectorOut.model_validate(sector).model_dump(),
        irrigation_system=IrrigationSystemOut.model_validate(irrig) if irrig else None,
        probe_count=probe_count,
    )


@router.get("/sectors/{sector_id}/status", response_model=SectorStatus)
async def get_sector_status(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    now = datetime.now(UTC)

    # Latest recommendation
    latest_rec = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Rootzone from recommendation inputs
    swc_current = None
    swc_source = None
    depletion_pct = None
    if latest_rec and latest_rec.inputs_snapshot:
        snap = latest_rec.inputs_snapshot
        swc_current = snap.get("swc_current")
        taw_mm = snap.get("taw_mm")
        depletion_mm = snap.get("depletion_mm")
        if taw_mm and depletion_mm is not None and taw_mm > 0:
            depletion_pct = round(depletion_mm / taw_mm * 100, 1)

    # Active alerts
    alerts = (
        await db.execute(
            select(Alert).where(Alert.sector_id == sector_id, Alert.is_active.is_(True))
        )
    ).scalars().all()
    crit = sum(1 for a in alerts if a.severity == "critical")
    warn = sum(1 for a in alerts if a.severity == "warning")
    info = sum(1 for a in alerts if a.severity == "info")

    # Last irrigation
    last_event = (
        await db.execute(
            select(IrrigationEvent)
            .where(IrrigationEvent.sector_id == sector_id)
            .order_by(IrrigationEvent.start_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Probe health
    probes = (
        await db.execute(select(Probe).where(Probe.sector_id == sector_id))
    ).scalars().all()

    probe_summaries = [
        ProbeHealthSummary(
            probe_id=p.id,
            external_id=p.external_id,
            health_status=p.health_status,
            last_reading_at=p.last_reading_at,
        )
        for p in probes
    ]

    # Data freshness
    freshness_hours = None
    if probes:
        reading_times = [p.last_reading_at for p in probes if p.last_reading_at]
        if reading_times:
            latest = max(reading_times)
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=UTC)
            freshness_hours = round((now - latest).total_seconds() / 3600, 1)

    # Rootzone status label
    def rootzone_label(depletion_pct):
        if depletion_pct is None:
            return "unknown"
        if depletion_pct < 20:
            return "wet"
        if depletion_pct < 60:
            return "optimal"
        if depletion_pct < 85:
            return "dry"
        return "critical"

    return SectorStatus(
        sector_id=sector_id,
        sector_name=sector.name,
        crop_type=sector.crop_type,
        current_stage=sector.current_phenological_stage,
        swc_current=swc_current,
        swc_source=swc_source,
        depletion_pct=depletion_pct,
        latest_recommendation_id=latest_rec.id if latest_rec else None,
        latest_action=latest_rec.action if latest_rec else None,
        latest_confidence_score=latest_rec.confidence_score if latest_rec else None,
        latest_confidence_level=latest_rec.confidence_level if latest_rec else None,
        latest_irrigation_depth_mm=latest_rec.irrigation_depth_mm if latest_rec else None,
        latest_runtime_min=latest_rec.irrigation_runtime_min if latest_rec else None,
        recommendation_generated_at=latest_rec.generated_at if latest_rec else None,
        active_alerts_critical=crit,
        active_alerts_warning=warn,
        active_alerts_info=info,
        last_irrigated_at=last_event.start_time if last_event else None,
        last_applied_mm=last_event.applied_mm if last_event else None,
        probes=probe_summaries,
        data_freshness_hours=freshness_hours,
    )


@router.post("/plots/{plot_id}/sectors", response_model=SectorOut, status_code=201)
async def create_sector(plot_id: str, body: SectorCreate, db: AsyncSession = Depends(get_db)):
    plot = await db.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, detail="Plot not found")
    sector = Sector(plot_id=plot_id, **body.model_dump())
    db.add(sector)
    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)


@router.post("/sectors/{sector_id}/irrigation-systems", response_model=IrrigationSystemOut, status_code=201)
async def create_or_replace_irrigation_system(
    sector_id: str,
    body: IrrigationSystemCreate,
    db: AsyncSession = Depends(get_db),
):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")
    # Remove existing if any
    existing = (
        await db.execute(select(IrrigationSystem).where(IrrigationSystem.sector_id == sector_id))
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()
    irrig = IrrigationSystem(sector_id=sector_id, **body.model_dump())
    db.add(irrig)
    await db.commit()
    await db.refresh(irrig)
    return IrrigationSystemOut.model_validate(irrig)


@router.put("/sectors/{sector_id}", response_model=SectorOut)
async def update_sector(sector_id: str, body: SectorUpdate, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(sector, k, v)
    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)

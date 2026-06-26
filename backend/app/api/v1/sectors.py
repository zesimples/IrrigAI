from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.models import (
    Alert,
    CropProfileTemplate,
    IrrigationEvent,
    IrrigationSystem,
    Plot,
    Probe,
    ProbeDepth,
    Recommendation,
    Sector,
    SectorCropProfile,
)
from app.schemas.common import PaginatedResponse
from app.schemas.recommendation import StressProjectionOut
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
    access: Access,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await access.plot(plot_id)

    offset = (page - 1) * page_size
    total = (
        await db.execute(
            select(func.count()).select_from(Sector).where(Sector.plot_id == plot_id, Sector.is_archived == False)  # noqa: E712
        )
    ).scalar_one()
    sectors = (
        await db.execute(
            select(Sector).where(Sector.plot_id == plot_id, Sector.is_archived == False).offset(offset).limit(page_size)  # noqa: E712
        )
    ).scalars().all()
    return PaginatedResponse(
        items=[SectorOut.model_validate(s) for s in sectors],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sectors/{sector_id}", response_model=SectorDetail)
async def get_sector(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    sector = await access.sector(sector_id)

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
async def get_sector_status(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    sector = await access.sector(sector_id)

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
    stress_proj_out: StressProjectionOut | None = None
    if latest_rec and latest_rec.inputs_snapshot:
        snap = latest_rec.inputs_snapshot
        swc_current = snap.get("swc_current")
        taw_mm = snap.get("taw_mm")
        depletion_mm = snap.get("depletion_mm")
        if taw_mm and depletion_mm is not None and taw_mm > 0:
            depletion_pct = round(depletion_mm / taw_mm * 100, 1)
        if "stress_projection" in snap:
            try:
                stress_proj_out = StressProjectionOut.model_validate(snap["stress_projection"])
            except Exception:
                pass

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

    # Probe calibration only applies to VWC moisture sensors. Tension/Watermark
    # sectors (e.g. the Olival at Herdade do Esporão) have no VWC depth, so the
    # "Calibração AI" button is disabled for them in the UI.
    calibration_available = False
    if probes:
        vwc_depth = (
            await db.execute(
                select(ProbeDepth.id)
                .where(
                    ProbeDepth.probe_id.in_([p.id for p in probes]),
                    ProbeDepth.sensor_type.in_(("soil_moisture", "moisture")),
                )
                .limit(1)
            )
        ).first()
        calibration_available = vwc_depth is not None

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
        # "low" is only valid when there are no probe readings at all.
        # Upgrade stored "low" to "medium" for sectors that have probe data
        # (covers recommendations generated before this rule was introduced).
        latest_confidence_level=(
            "medium"
            if latest_rec and latest_rec.confidence_level == "low" and freshness_hours is not None
            else (latest_rec.confidence_level if latest_rec else None)
        ),
        latest_irrigation_depth_mm=latest_rec.irrigation_depth_mm if latest_rec else None,
        latest_runtime_min=latest_rec.irrigation_runtime_min if latest_rec else None,
        recommendation_generated_at=latest_rec.generated_at if latest_rec else None,
        active_alerts_critical=crit,
        active_alerts_warning=warn,
        active_alerts_info=info,
        last_irrigated_at=last_event.start_time if last_event else None,
        last_applied_mm=last_event.applied_mm if last_event else None,
        probes=probe_summaries,
        calibration_available=calibration_available,
        data_freshness_hours=freshness_hours,
        stress_projection=stress_proj_out,
    )


@router.post("/plots/{plot_id}/sectors", response_model=SectorOut, status_code=201)
async def create_sector(
    plot_id: str,
    body: SectorCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.plot(plot_id)
    sector = Sector(plot_id=plot_id, **body.model_dump())
    db.add(sector)
    await db.flush()

    # Auto-materialise a crop profile from the system-default template for this
    # crop type (if one exists), so the sector has agronomic Kc/root-depth values
    # straight away. Mirrors the seed and the reset endpoint.
    tpl = (
        await db.execute(
            select(CropProfileTemplate).where(
                CropProfileTemplate.crop_type == sector.crop_type,
                CropProfileTemplate.is_system_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if tpl:
        db.add(
            SectorCropProfile(
                sector_id=sector.id,
                source_template_id=tpl.id,
                crop_type=tpl.crop_type,
                mad=tpl.mad,
                root_depth_mature_m=tpl.root_depth_mature_m,
                root_depth_young_m=tpl.root_depth_young_m,
                maturity_age_years=tpl.maturity_age_years,
                stages=tpl.stages,
                is_customized=False,
            )
        )

    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)


@router.post("/sectors/{sector_id}/irrigation-systems", response_model=IrrigationSystemOut, status_code=201)
async def create_or_replace_irrigation_system(
    sector_id: str,
    body: IrrigationSystemCreate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
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


@router.get("/sectors/{sector_id}/stress-projection", response_model=StressProjectionOut)
async def get_live_stress_projection(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    """Compute a fresh stress projection for a sector using current sensor + forecast data."""
    from datetime import date as _date

    from app.engine import et0 as et0_mod
    from app.engine import probe_interpreter, water_balance
    from app.engine.pipeline import build_sector_context, build_weather_context
    from app.engine.stress_projection import StressProjector

    sector = await access.sector(sector_id)

    plot = await db.get(Plot, sector.plot_id)
    if not plot:
        raise HTTPException(404, detail="Plot not found")

    ctx = await build_sector_context(sector_id, db)
    weather = await build_weather_context(plot.farm_id, db)

    et0_val, _ = et0_mod.compute_et0(weather.today, weather.lat or 38.57, weather.elevation_m)
    probes = await probe_interpreter.interpret_probes(ctx, db)
    wb = water_balance.build_water_balance(ctx, probes.rootzone.swc_current)

    stress = StressProjector().project(
        current_depletion_mm=wb.depletion_mm,
        taw_mm=wb.taw_mm,
        mad=ctx.mad,
        forecast_et0=[w.et0_mm for w in weather.forecast[:3]],
        kc=ctx.kc,
        forecast_rain=[
            (w.rainfall_mm or 0.0, w.rainfall_probability_pct or 0.0)
            for w in weather.forecast[:3]
        ],
        rainfall_effectiveness=ctx.rainfall_effectiveness,
        sector_id=sector_id,
        today=_date.today(),
    )

    return StressProjectionOut(
        current_depletion_pct=stress.current_depletion_pct,
        hours_to_stress=stress.hours_to_stress,
        stress_date=stress.stress_date.isoformat() if stress.stress_date else None,
        urgency=stress.urgency,
        message_pt=stress.message_pt,
        message_en=stress.message_en,
        projections=[
            {
                "date": p.date.isoformat(),
                "projected_etc_mm": p.projected_etc_mm,
                "projected_rain_mm": p.projected_rain_mm,
                "projected_depletion_mm": p.projected_depletion_mm,
                "projected_depletion_pct": p.projected_depletion_pct,
                "stress_triggered": p.stress_triggered,
            }
            for p in stress.projections
        ],
    )


@router.put("/sectors/{sector_id}", response_model=SectorOut)
async def update_sector(
    sector_id: str,
    body: SectorUpdate,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    sector = await access.sector(sector_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(sector, k, v)
    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)


@router.post("/sectors/{sector_id}/archive", response_model=SectorOut)
async def archive_sector(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    sector = await access.sector(sector_id)
    sector.is_archived = True
    sector.archived_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)


@router.post("/sectors/{sector_id}/unarchive", response_model=SectorOut)
async def unarchive_sector(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    sector = await access.sector(sector_id)
    sector.is_archived = False
    sector.archived_at = None
    await db.commit()
    await db.refresh(sector)
    return SectorOut.model_validate(sector)

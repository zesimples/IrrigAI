"""Flow rate reference endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Farm, Flowmeter, Plot, Sector
from app.models.flowmeter_reference import FlowmeterReference
from app.schemas.flowmeter import FlowmeterReferenceManualSet, FlowmeterReferenceOut

router = APIRouter(tags=["flowmeter"])


async def _get_flowmeter_and_sector(sector_id: str, db: AsyncSession):
    result = await db.execute(
        select(Flowmeter, Sector)
        .join(Sector, Flowmeter.sector_id == Sector.id)
        .where(Flowmeter.sector_id == sector_id, Flowmeter.is_active.is_(True))
    )
    row = result.first()
    if row is None:
        raise HTTPException(404, detail="No active flowmeter for this sector")
    return row


def _ref_to_out(ref: FlowmeterReference, sector: Sector | None = None) -> FlowmeterReferenceOut:
    return FlowmeterReferenceOut(
        id=ref.id,
        flowmeter_id=ref.flowmeter_id,
        reference_rate_m3_ha=ref.reference_rate_m3_ha if ref.status != "insufficient" else None,
        tolerance_pct=ref.tolerance_pct,
        upper_limit_m3_ha=ref.upper_limit_m3_ha if ref.status != "insufficient" else None,
        lower_limit_m3_ha=ref.lower_limit_m3_ha if ref.status != "insufficient" else None,
        num_events_analyzed=ref.num_events_analyzed,
        std_dev=ref.std_dev,
        status=ref.status,
        computed_at=ref.computed_at,
        is_manual_override=ref.is_manual_override,
        sector_id=str(sector.id) if sector else None,
        sector_name=sector.name if sector else None,
        crop_type=sector.crop_type if sector else None,
    )


@router.get("/sectors/{sector_id}/flowmeter-reference", response_model=FlowmeterReferenceOut)
async def get_flowmeter_reference(sector_id: str, db: AsyncSession = Depends(get_db)):
    fm, sector = await _get_flowmeter_and_sector(sector_id, db)
    result = await db.execute(
        select(FlowmeterReference).where(FlowmeterReference.flowmeter_id == str(fm.id))
    )
    ref = result.scalar_one_or_none()
    if ref is None:
        raise HTTPException(404, detail="Reference not yet computed for this flowmeter")
    return _ref_to_out(ref, sector)


@router.post(
    "/sectors/{sector_id}/flowmeter-reference/recompute",
    response_model=FlowmeterReferenceOut,
)
async def recompute_flowmeter_reference(sector_id: str, db: AsyncSession = Depends(get_db)):
    fm, sector = await _get_flowmeter_and_sector(sector_id, db)
    from app.services.flowmeter_reference import FlowmeterReferenceService
    svc = FlowmeterReferenceService()
    ref = await svc.compute_and_save(
        flowmeter_id=str(fm.id),
        sector_id=sector_id,
        sector_name=sector.name,
        db=db,
    )
    await db.commit()
    return _ref_to_out(ref, sector)


@router.put("/sectors/{sector_id}/flowmeter-reference", response_model=FlowmeterReferenceOut)
async def set_manual_flowmeter_reference(
    sector_id: str,
    body: FlowmeterReferenceManualSet,
    db: AsyncSession = Depends(get_db),
):
    from app.models.base import new_uuid

    fm, sector = await _get_flowmeter_and_sector(sector_id, db)
    result = await db.execute(
        select(FlowmeterReference).where(FlowmeterReference.flowmeter_id == str(fm.id))
    )
    ref = result.scalar_one_or_none()
    upper = round(body.reference_rate_m3_ha * (1 + body.tolerance_pct / 100), 4)
    lower = round(body.reference_rate_m3_ha * (1 - body.tolerance_pct / 100), 4)
    now = datetime.now(UTC)

    if ref is None:
        ref = FlowmeterReference(
            id=new_uuid(),
            flowmeter_id=str(fm.id),
            reference_rate_m3_ha=body.reference_rate_m3_ha,
            tolerance_pct=body.tolerance_pct,
            upper_limit_m3_ha=upper,
            lower_limit_m3_ha=lower,
            num_events_analyzed=0,
            std_dev=0.0,
            status="established",
            computed_at=now,
            is_manual_override=True,
        )
        db.add(ref)
    else:
        ref.reference_rate_m3_ha = body.reference_rate_m3_ha
        ref.tolerance_pct = body.tolerance_pct
        ref.upper_limit_m3_ha = upper
        ref.lower_limit_m3_ha = lower
        ref.status = "established"
        ref.computed_at = now
        ref.is_manual_override = True

    await db.commit()
    return _ref_to_out(ref, sector)


@router.get("/farms/{farm_id}/flowmeter-references", response_model=list[FlowmeterReferenceOut])
async def get_farm_flowmeter_references(farm_id: str, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(404, detail="Farm not found")

    result = await db.execute(
        select(FlowmeterReference, Flowmeter, Sector)
        .join(Flowmeter, FlowmeterReference.flowmeter_id == Flowmeter.id)
        .join(Sector, Flowmeter.sector_id == Sector.id)
        .join(Plot, Sector.plot_id == Plot.id)
        .where(Plot.farm_id == farm_id, Flowmeter.is_active.is_(True))
        .order_by(Sector.name)
    )
    rows = result.all()
    return [_ref_to_out(ref, sector) for ref, _fm, sector in rows]


@router.get("/farms/{farm_id}/flowmeter-flow-rate-alerts")
async def get_farm_flow_rate_alerts(farm_id: str, db: AsyncSession = Depends(get_db)):
    from datetime import timedelta

    from app.core.enums import AlertType
    from app.models.alert import Alert

    alert_types = [
        AlertType.FLOWMETER_FLOW_RATE_HIGH,
        AlertType.FLOWMETER_FLOW_RATE_LOW,
        AlertType.FLOWMETER_MID_EVENT_ZEROS,
    ]
    cutoff = datetime.now(UTC) - timedelta(days=30)
    result = await db.execute(
        select(Alert)
        .where(
            Alert.farm_id == farm_id,
            Alert.alert_type.in_([t.value for t in alert_types]),
            Alert.created_at >= cutoff,
        )
        .order_by(Alert.created_at.desc())
        .limit(100)
    )
    alerts = result.scalars().all()

    return [
        {
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title_pt": a.title_pt,
            "title_en": a.title_en,
            "description_pt": a.description_pt,
            "description_en": a.description_en,
            "sector_id": a.sector_id,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "data": a.data,
        }
        for a in alerts
    ]

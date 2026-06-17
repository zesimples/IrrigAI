from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Access
from app.database import get_db
from app.models import Alert
from app.schemas.alert import AcknowledgeRequest, AlertOut
from app.schemas.common import PaginatedResponse
from app.services.audit_service import ALERT_ACKNOWLEDGED, ALERT_RESOLVED, audit

router = APIRouter(tags=["alerts"])


@router.get("/farms/{farm_id}/alerts", response_model=PaginatedResponse[AlertOut])
async def list_alerts(
    farm_id: str,
    access: Access,
    severity: str | None = Query(None, description="Filter by severity: critical, warning, info"),
    sector_id: str | None = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await access.farm(farm_id)

    q = select(Alert).where(Alert.farm_id == farm_id)
    count_q = select(func.count()).select_from(Alert).where(Alert.farm_id == farm_id)

    if active_only:
        q = q.where(Alert.is_active.is_(True))
        count_q = count_q.where(Alert.is_active.is_(True))
    if severity:
        q = q.where(Alert.severity == severity)
        count_q = count_q.where(Alert.severity == severity)
    if sector_id:
        q = q.where(Alert.sector_id == sector_id)
        count_q = count_q.where(Alert.sector_id == sector_id)

    total = (await db.execute(count_q)).scalar_one()
    offset = (page - 1) * page_size
    alerts = (
        await db.execute(q.order_by(Alert.created_at.desc()).offset(offset).limit(page_size))
    ).scalars().all()

    return PaginatedResponse(
        items=[AlertOut.model_validate(a) for a in alerts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/alerts/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    alert = await access.alert(alert_id)
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: str,
    body: AcknowledgeRequest,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    alert = await access.alert(alert_id)
    alert.acknowledged_at = datetime.now(UTC)
    await audit.log(ALERT_ACKNOWLEDGED, "alert", alert_id, db,
                    after_data={"acknowledged_at": alert.acknowledged_at.isoformat()})
    await db.commit()
    await db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(alert_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    alert = await access.alert(alert_id)
    alert.is_active = False
    await audit.log(ALERT_RESOLVED, "alert", alert_id, db,
                    before_data={"is_active": True}, after_data={"is_active": False})
    await db.commit()
    await db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/farms/{farm_id}/alerts/resolve-all")
async def resolve_all_alerts(farm_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    """Resolve all active alerts for a farm in one call."""
    await access.farm(farm_id)

    active_alerts = (
        await db.execute(
            select(Alert).where(Alert.farm_id == farm_id, Alert.is_active.is_(True))
        )
    ).scalars().all()

    for alert in active_alerts:
        alert.is_active = False
        await audit.log(ALERT_RESOLVED, "alert", alert.id, db,
                        before_data={"is_active": True}, after_data={"is_active": False})

    await db.commit()
    return {"resolved": len(active_alerts), "farm_id": farm_id}


@router.post("/farms/{farm_id}/alerts/detect")
async def trigger_anomaly_detection(
    farm_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    from app.services.anomaly_service import run_for_farm

    await access.farm(farm_id)

    anomalies = await run_for_farm(farm_id, db)
    return {"detected": len(anomalies), "farm_id": farm_id}


@router.post("/farms/{farm_id}/alerts/run")
async def run_alert_engine(farm_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    """Trigger the alert engine for a farm (on-demand)."""
    from app.alerts.engine import AlertEngine

    await access.farm(farm_id)

    engine = AlertEngine()
    alerts = await engine.run_farm_alerts(farm_id, db)
    return {"generated": len(alerts), "farm_id": farm_id}

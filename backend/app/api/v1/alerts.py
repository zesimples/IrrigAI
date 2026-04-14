from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Alert, Farm, Plot, Sector
from app.schemas.alert import AcknowledgeRequest, AlertOut
from app.schemas.common import PaginatedResponse
from app.services.audit_service import ALERT_ACKNOWLEDGED, ALERT_RESOLVED, audit

router = APIRouter(tags=["alerts"])


@router.get("/farms/{farm_id}/alerts", response_model=PaginatedResponse[AlertOut])
async def list_alerts(
    farm_id: str,
    severity: str | None = Query(None, description="Filter by severity: critical, warning, info"),
    sector_id: str | None = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")

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
async def get_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, detail="Alert not found")
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(alert_id: str, body: AcknowledgeRequest, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, detail="Alert not found")
    alert.acknowledged_at = datetime.now(UTC)
    await audit.log(ALERT_ACKNOWLEDGED, "alert", alert_id, db,
                    after_data={"acknowledged_at": alert.acknowledged_at.isoformat()})
    await db.commit()
    await db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, detail="Alert not found")
    alert.is_active = False
    await audit.log(ALERT_RESOLVED, "alert", alert_id, db,
                    before_data={"is_active": True}, after_data={"is_active": False})
    await db.commit()
    await db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/farms/{farm_id}/alerts/detect")
async def trigger_anomaly_detection(farm_id: str, db: AsyncSession = Depends(get_db)):
    from app.services.anomaly_service import run_for_farm

    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")

    anomalies = await run_for_farm(farm_id, db)
    return {"detected": len(anomalies), "farm_id": farm_id}


@router.post("/farms/{farm_id}/alerts/run")
async def run_alert_engine(farm_id: str, db: AsyncSession = Depends(get_db)):
    """Trigger the alert engine for a farm (on-demand)."""
    from app.alerts.engine import AlertEngine

    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")

    engine = AlertEngine()
    alerts = await engine.run_farm_alerts(farm_id, db)
    return {"generated": len(alerts), "farm_id": farm_id}

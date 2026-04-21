"""GDD (Growing Degree Days) phenology API.

GET  /sectors/{sector_id}/gdd-status        — get GDD status for a sector
GET  /farms/{farm_id}/gdd-status            — get GDD status for all farm sectors
POST /sectors/{sector_id}/gdd-status/confirm — confirm suggested phenological stage
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.engine.gdd_tracker import GDDStatus, GDDTracker
from app.models import Farm, Sector
from app.services.audit_service import audit

router = APIRouter(tags=["gdd"])

_tracker = GDDTracker()


# ── Response schemas ──────────────────────────────────────────────────────────

class GDDStatusOut(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    reference_date: str
    accumulated_gdd: float
    tbase_c: float
    current_stage: str | None
    suggested_stage: str | None
    suggested_stage_name_pt: str | None
    suggested_stage_name_en: str | None
    stage_changed: bool
    days_in_current_stage: int | None
    next_stage: str | None
    next_stage_name_pt: str | None
    gdd_to_next_stage: float | None
    confidence: str
    missing_weather_days: int
    suggestion_pt: str | None
    suggestion_en: str | None


class ConfirmStageRequest(BaseModel):
    stage: str | None = None            # if None, confirm the suggested stage


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sectors/{sector_id}/gdd-status", response_model=GDDStatusOut)
async def get_sector_gdd_status(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    status = await _tracker.compute_accumulated_gdd(sector_id, db)
    if status is None:
        raise HTTPException(
            404,
            detail="GDD tracking not available for this sector (missing crop profile or reference date)",
        )

    return _to_out(status)


@router.get("/farms/{farm_id}/gdd-status", response_model=list[GDDStatusOut])
async def get_farm_gdd_status(farm_id: str, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")

    statuses = await _tracker.compute_gdd_for_all_sectors(farm_id, db)
    return [_to_out(s) for s in statuses]


@router.post("/sectors/{sector_id}/gdd-status/confirm", response_model=dict)
async def confirm_gdd_stage(
    sector_id: str,
    body: ConfirmStageRequest,
    db: AsyncSession = Depends(get_db),
):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    if body.stage:
        new_stage = body.stage
    else:
        status = await _tracker.compute_accumulated_gdd(sector_id, db)
        if status is None or not status.suggested_stage:
            raise HTTPException(404, detail="No GDD-suggested stage available")
        new_stage = status.suggested_stage

    before = {"current_phenological_stage": sector.current_phenological_stage}
    sector.current_phenological_stage = new_stage
    await audit.log(
        "phenological_stage_confirmed_via_gdd",
        "sector",
        sector_id,
        db,
        before_data=before,
        after_data={"current_phenological_stage": new_stage},
    )
    await db.commit()

    return {
        "confirmed": True,
        "stage": new_stage,
        "sector_id": sector_id,
    }


def _to_out(s: GDDStatus) -> GDDStatusOut:
    return GDDStatusOut(
        sector_id=s.sector_id,
        sector_name=s.sector_name,
        crop_type=s.crop_type,
        reference_date=s.reference_date.isoformat(),
        accumulated_gdd=s.accumulated_gdd,
        tbase_c=s.tbase_c,
        current_stage=s.current_stage,
        suggested_stage=s.suggested_stage,
        suggested_stage_name_pt=s.suggested_stage_name_pt,
        suggested_stage_name_en=s.suggested_stage_name_en,
        stage_changed=s.stage_changed,
        days_in_current_stage=s.days_in_current_stage,
        next_stage=s.next_stage,
        next_stage_name_pt=s.next_stage_name_pt,
        gdd_to_next_stage=s.gdd_to_next_stage,
        confidence=s.confidence,
        missing_weather_days=s.missing_weather_days,
        suggestion_pt=s.suggestion_pt,
        suggestion_en=s.suggestion_en,
    )

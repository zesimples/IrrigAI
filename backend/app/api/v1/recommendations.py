from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Farm, Probe, Recommendation, RecommendationReason, Sector
from app.models.sector_override import SectorOverride
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.recommendation import (
    AcceptRequest,
    OverrideRequest,
    ReasonOut,
    RecommendationDetail,
    RecommendationOut,
    RejectRequest,
    StressProjectionOut,
)
from app.services.audit_service import audit
from app.services.audit_service import (
    RECOMMENDATION_ACCEPTED,
    RECOMMENDATION_GENERATED,
    RECOMMENDATION_OVERRIDDEN,
    RECOMMENDATION_REJECTED,
    OVERRIDE_CREATED,
)
from app.services.recommendation_service import generate_for_farm, generate_recommendation

router = APIRouter(tags=["recommendations"])


@router.get("/sectors/{sector_id}/recommendations", response_model=PaginatedResponse[RecommendationOut])
async def list_sector_recommendations(
    sector_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    offset = (page - 1) * page_size
    total = (
        await db.execute(
            select(func.count()).select_from(Recommendation).where(
                Recommendation.sector_id == sector_id
            )
        )
    ).scalar_one()
    recs = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.sector_id == sector_id)
            .order_by(Recommendation.generated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    return PaginatedResponse(
        items=[RecommendationOut.model_validate(r) for r in recs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetail)
async def get_recommendation(rec_id: str, db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, detail="Recommendation not found")
    reasons = (
        await db.execute(
            select(RecommendationReason)
            .where(RecommendationReason.recommendation_id == rec_id)
            .order_by(RecommendationReason.order)
        )
    ).scalars().all()
    base = RecommendationOut.model_validate(rec).model_dump()

    # Upgrade stored "low" → "medium" when the sector has probe readings.
    # "low" is only valid when has_data=False (no readings at all).
    if base.get("confidence_level") == "low":
        probes = (
            await db.execute(select(Probe).where(Probe.sector_id == rec.sector_id))
        ).scalars().all()
        has_probe_data = any(p.last_reading_at is not None for p in probes)
        if has_probe_data:
            base["confidence_level"] = "medium"

    # Extract stress projection from inputs_snapshot if present
    snap = rec.inputs_snapshot or {}
    stress_proj_out: StressProjectionOut | None = None
    if "stress_projection" in snap:
        try:
            stress_proj_out = StressProjectionOut.model_validate(snap["stress_projection"])
        except Exception:
            pass

    return RecommendationDetail(
        **base,
        reasons=[ReasonOut.model_validate(r) for r in reasons],
        inputs_snapshot=snap,
        computation_log=rec.computation_log or {},
        stress_projection=stress_proj_out,
    )


@router.post("/sectors/{sector_id}/recommendations/generate", response_model=RecommendationOut, status_code=201)
async def generate_sector_recommendation(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")
    try:
        rec, _ = await generate_recommendation(sector_id, db)
    except Exception as exc:
        raise HTTPException(500, detail=f"Engine error: {exc}") from exc
    return RecommendationOut.model_validate(rec)


@router.post("/farms/{farm_id}/recommendations/generate", response_model=list[RecommendationOut], status_code=201)
async def generate_farm_recommendations(farm_id: str, db: AsyncSession = Depends(get_db)):
    farm = await db.get(Farm, farm_id)
    if not farm:
        raise HTTPException(404, detail="Farm not found")
    try:
        results = await generate_for_farm(farm_id, db)
    except Exception as exc:
        raise HTTPException(500, detail=f"Engine error: {exc}") from exc
    return [RecommendationOut.model_validate(rec) for rec, _ in results]


@router.post("/recommendations/{rec_id}/accept", response_model=RecommendationOut)
async def accept_recommendation(rec_id: str, body: AcceptRequest, db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, detail="Recommendation not found")
    before = {"is_accepted": rec.is_accepted}
    rec.is_accepted = True
    rec.accepted_at = datetime.now(UTC)
    if body.notes:
        rec.override_notes = body.notes
    await audit.log(RECOMMENDATION_ACCEPTED, "recommendation", rec_id, db,
                    before_data=before, after_data={"is_accepted": True, "notes": body.notes})
    await db.commit()
    await db.refresh(rec)
    return RecommendationOut.model_validate(rec)


@router.post("/recommendations/{rec_id}/reject", response_model=RecommendationOut)
async def reject_recommendation(rec_id: str, body: RejectRequest, db: AsyncSession = Depends(get_db)):
    rec = await db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, detail="Recommendation not found")
    before = {"is_accepted": rec.is_accepted}
    rec.is_accepted = False
    if body.notes:
        rec.override_notes = body.notes
    await audit.log(RECOMMENDATION_REJECTED, "recommendation", rec_id, db,
                    before_data=before, after_data={"is_accepted": False, "notes": body.notes})
    await db.commit()
    await db.refresh(rec)
    return RecommendationOut.model_validate(rec)


@router.post("/recommendations/{rec_id}/override", response_model=RecommendationOut)
async def override_recommendation(
    rec_id: str, body: OverrideRequest, db: AsyncSession = Depends(get_db)
):
    rec = await db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, detail="Recommendation not found")

    # Capture original values for audit
    before = {
        "action": rec.action,
        "irrigation_depth_mm": rec.irrigation_depth_mm,
        "irrigation_runtime_min": rec.irrigation_runtime_min,
        "override_notes": rec.override_notes,
    }

    # Resolve override values (new fields take precedence over legacy fields)
    depth_mm = body.custom_depth_mm or body.irrigation_depth_mm
    runtime_min = body.custom_runtime_min or body.irrigation_runtime_min
    reason = body.override_reason or body.notes or ""

    if body.custom_action:
        rec.action = body.custom_action
    if depth_mm is not None:
        rec.irrigation_depth_mm = depth_mm
    if runtime_min is not None:
        rec.irrigation_runtime_min = runtime_min
    rec.override_notes = reason
    rec.is_accepted = True
    rec.accepted_at = datetime.now(UTC)

    after = {
        "action": rec.action,
        "irrigation_depth_mm": rec.irrigation_depth_mm,
        "irrigation_runtime_min": rec.irrigation_runtime_min,
        "override_notes": rec.override_notes,
        "strategy": body.override_strategy,
    }

    await audit.log(RECOMMENDATION_OVERRIDDEN, "recommendation", rec_id, db,
                    before_data=before, after_data=after)

    # Create sector-level override for "until_next_stage" strategy
    if body.override_strategy == "until_next_stage":
        override_type = "fixed_depth" if depth_mm is not None else "force_irrigate"
        sector_override = SectorOverride(
            sector_id=rec.sector_id,
            override_type=override_type,
            value=depth_mm,
            reason=reason,
            override_strategy=body.override_strategy,
            is_active=True,
        )
        db.add(sector_override)
        await db.flush()
        await audit.log(OVERRIDE_CREATED, "sector_override", sector_override.id, db,
                        after_data={"sector_id": rec.sector_id, "type": override_type, "reason": reason})

    await db.commit()
    await db.refresh(rec)
    return RecommendationOut.model_validate(rec)

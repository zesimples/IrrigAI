"""Auto-calibration API endpoints.

GET  /sectors/{sector_id}/auto-calibration   — get soil validation result
POST /sectors/{sector_id}/auto-calibration/accept   — switch to suggested preset
POST /sectors/{sector_id}/auto-calibration/dismiss  — suppress for 30 days
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.engine.auto_calibration import AutoCalibrationResult, AutoCalibrationService
from app.models import Plot, Sector, SectorCropProfile, SoilPreset
from app.services.audit_service import audit

router = APIRouter(tags=["auto-calibration"])

_service = AutoCalibrationService()


# ── Response schemas ──────────────────────────────────────────────────────────

class SoilPresetMatchOut(BaseModel):
    preset_id: str
    preset_name_pt: str
    preset_name_en: str
    preset_fc_pct: float
    preset_wp_pct: float
    distance: float


class SoilMatchResultOut(BaseModel):
    current_preset: SoilPresetMatchOut | None
    best_match: SoilPresetMatchOut
    all_matches: list[SoilPresetMatchOut]
    status: str                         # "validated" | "better_match_found" | "no_good_match"


class ObservedSoilPointsOut(BaseModel):
    observed_fc_pct: float
    observed_refill_pct: float
    num_cycles: int
    consistency: float
    analysis_depths_cm: list[int]


class AutoCalibrationOut(BaseModel):
    sector_id: str
    sector_name: str
    observed: ObservedSoilPointsOut
    match: SoilMatchResultOut
    suggestion_pt: str
    suggestion_en: str
    generated_at: datetime
    dismissed: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sectors/{sector_id}/auto-calibration", response_model=AutoCalibrationOut)
async def get_auto_calibration(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    # Check if suppressed
    now = datetime.now(UTC)
    if (
        sector.auto_calibration_dismissed_until is not None
        and sector.auto_calibration_dismissed_until > now
    ):
        raise HTTPException(
            404,
            detail=f"Auto-calibration dismissed until {sector.auto_calibration_dismissed_until.isoformat()}",
        )

    result: AutoCalibrationResult | None = await _service.analyze_sector(sector_id, db)
    if result is None:
        raise HTTPException(
            404,
            detail="Insufficient data for auto-calibration (need ≥3 irrigation cycles in last 60 days)",
        )

    return _to_out(result)


@router.post("/sectors/{sector_id}/auto-calibration/accept", response_model=dict)
async def accept_auto_calibration(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    result = await _service.analyze_sector(sector_id, db)
    if result is None:
        raise HTTPException(404, detail="No calibration result available")

    if result.match.status != "better_match_found":
        raise HTTPException(
            400,
            detail=f"Accept is only available when status is 'better_match_found' (current: {result.match.status})",
        )

    best = result.match.best_match
    preset = await db.get(SoilPreset, best.preset_id)
    if not preset:
        raise HTTPException(404, detail="Suggested soil preset not found")

    # Update the Plot's soil values (engine reads from Plot/SectorCropProfile)
    plot = await db.get(Plot, sector.plot_id)
    before: dict = {}
    after: dict = {}

    if plot:
        before = {
            "soil_preset_id": plot.soil_preset_id,
            "field_capacity": plot.field_capacity,
            "wilting_point": plot.wilting_point,
        }
        plot.soil_preset_id = preset.id
        plot.field_capacity = preset.field_capacity
        plot.wilting_point = preset.wilting_point
        plot.soil_texture = preset.texture
        after = {
            "soil_preset_id": preset.id,
            "field_capacity": preset.field_capacity,
            "wilting_point": preset.wilting_point,
        }

    # Also update sector crop profile if it has soil overrides
    scp_result = await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )
    scp = scp_result.scalar_one_or_none()
    if scp and (scp.field_capacity is not None or scp.soil_preset_id is not None):
        scp.soil_preset_id = preset.id
        scp.field_capacity = preset.field_capacity
        scp.wilting_point = preset.wilting_point

    await audit.log(
        "soil_preset_updated_by_calibration",
        "sector",
        sector_id,
        db,
        before_data=before,
        after_data={**after, "preset_name": preset.name_en},
    )
    await db.commit()

    return {
        "accepted": True,
        "preset_id": preset.id,
        "preset_name_pt": preset.name_pt,
        "preset_name_en": preset.name_en,
        "field_capacity": preset.field_capacity,
        "wilting_point": preset.wilting_point,
    }


@router.post("/sectors/{sector_id}/auto-calibration/dismiss", response_model=dict)
async def dismiss_auto_calibration(sector_id: str, db: AsyncSession = Depends(get_db)):
    sector = await db.get(Sector, sector_id)
    if not sector:
        raise HTTPException(404, detail="Sector not found")

    dismissed_until = datetime.now(UTC) + timedelta(days=30)
    sector.auto_calibration_dismissed_until = dismissed_until
    await db.commit()

    return {
        "dismissed": True,
        "dismissed_until": dismissed_until.isoformat(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_out(result: AutoCalibrationResult) -> AutoCalibrationOut:
    from app.engine.auto_calibration import ObservedSoilPoints, SoilMatchResult, SoilPresetMatch

    def _match_out(m: SoilPresetMatch) -> SoilPresetMatchOut:
        return SoilPresetMatchOut(
            preset_id=m.preset_id,
            preset_name_pt=m.preset_name_pt,
            preset_name_en=m.preset_name_en,
            preset_fc_pct=m.preset_fc_pct,
            preset_wp_pct=m.preset_wp_pct,
            distance=m.distance,
        )

    return AutoCalibrationOut(
        sector_id=result.sector_id,
        sector_name=result.sector_name,
        observed=ObservedSoilPointsOut(
            observed_fc_pct=result.observed.observed_fc_pct,
            observed_refill_pct=result.observed.observed_refill_pct,
            num_cycles=result.observed.num_cycles,
            consistency=result.observed.consistency,
            analysis_depths_cm=result.observed.analysis_depths_cm,
        ),
        match=SoilMatchResultOut(
            current_preset=_match_out(result.match.current_preset) if result.match.current_preset else None,
            best_match=_match_out(result.match.best_match),
            all_matches=[_match_out(m) for m in result.match.all_matches],
            status=result.match.status,
        ),
        suggestion_pt=result.suggestion_pt,
        suggestion_en=result.suggestion_en,
        generated_at=result.generated_at,
    )

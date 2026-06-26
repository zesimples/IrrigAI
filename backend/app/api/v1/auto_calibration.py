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

from app.access import Access
from app.database import get_db
from app.engine.auto_calibration import (
    CALIB_MAX_AGE_DAYS,
    AutoCalibrationResult,
    AutoCalibrationService,
)
from app.models import Plot, ProbeCalibration, SectorCropProfile, SoilPreset
from app.services.audit_service import audit
from app.services.probe_calibration_service import ProbeCalibrationService

router = APIRouter(tags=["auto-calibration"])

_service = AutoCalibrationService()
_calib_service = ProbeCalibrationService()

# Below this much movement (m³/m³) a recompute is reported as "no change" so the
# user gets honest feedback instead of an identical-looking "updated" toast.
_CHANGE_EPS_M3M3 = 0.005


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


class ProbeCalibrationOut(BaseModel):
    """Deterministically computed soil reference points from the probe's own VWC
    envelope. Field names are kept honest: this is a *calibrated CC* and an
    *effective refill line* (operational lower bound), not a measured true PMP."""

    sector_id: str
    observed_fc: float          # m³/m³ — calibrated CC (drained upper limit)
    observed_refill: float      # m³/m³ — effective refill / operational lower bound
    method: str                 # "cycles" | "envelope"
    num_cycles: int
    consistency: float
    window_days: int
    computed_at: datetime
    max_age_days: int = CALIB_MAX_AGE_DAYS
    # Delta vs the calibration that existed before this run, so the UI can give
    # honest feedback ("updated CC 41→49" vs "no change — already calibrated").
    previous_fc: float | None = None        # None on first-ever calibration
    previous_refill: float | None = None
    changed: bool = True                     # values meaningfully moved (or first run)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sectors/{sector_id}/auto-calibration", response_model=AutoCalibrationOut)
async def get_auto_calibration(sector_id: str, access: Access, db: AsyncSession = Depends(get_db)):
    sector = await access.sector(sector_id)

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


@router.post("/sectors/{sector_id}/auto-calibration/run", response_model=ProbeCalibrationOut)
async def run_probe_calibration(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger deterministic probe calibration for one sector.

    Computes calibrated CC / effective refill line from the sector's own VWC
    envelope (NOT an LLM) and saves it. Future recommendations pick it up through
    the shared soil-bound resolution path. Does not touch customized human soil
    settings — those still override calibration in the resolver.
    """
    await access.sector(sector_id)

    # Snapshot the previous bounds (by value) BEFORE compute_and_save mutates the row,
    # so we can report whether the recompute actually moved anything.
    existing = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
    )).scalar_one_or_none()
    prev_fc = existing.observed_fc if existing else None
    prev_refill = existing.observed_refill if existing else None

    saved = await _calib_service.compute_and_save(sector_id, db)
    if saved is None:
        raise HTTPException(
            422,
            detail=(
                "Insufficient or implausible probe data to calibrate this sector "
                "(need enough good-quality VWC readings with a plausible FC and a "
                "refill line clearly below it)."
            ),
        )

    if prev_fc is None or prev_refill is None:
        changed = True                        # first-ever calibration for this sector
    else:
        changed = (
            abs(prev_fc - saved.observed_fc) >= _CHANGE_EPS_M3M3
            or abs(prev_refill - saved.observed_refill) >= _CHANGE_EPS_M3M3
        )

    await audit.log(
        "probe_calibration_computed",
        "sector",
        sector_id,
        db,
        before_data=(
            {"observed_fc": prev_fc, "observed_refill": prev_refill}
            if existing else None
        ),
        after_data={
            "observed_fc": saved.observed_fc,
            "observed_refill": saved.observed_refill,
            "method": saved.method,
            "num_cycles": saved.num_cycles,
            "consistency": saved.consistency,
            "window_days": saved.window_days,
            "changed": changed,
        },
    )
    await db.commit()

    return ProbeCalibrationOut(
        sector_id=sector_id,
        observed_fc=saved.observed_fc,
        observed_refill=saved.observed_refill,
        method=saved.method,
        num_cycles=saved.num_cycles,
        consistency=saved.consistency,
        window_days=saved.window_days,
        computed_at=saved.computed_at,
        previous_fc=prev_fc,
        previous_refill=prev_refill,
        changed=changed,
    )


@router.post("/sectors/{sector_id}/auto-calibration/accept", response_model=dict)
async def accept_auto_calibration(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    sector = await access.sector(sector_id)

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
async def dismiss_auto_calibration(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    sector = await access.sector(sector_id)

    dismissed_until = datetime.now(UTC) + timedelta(days=30)
    sector.auto_calibration_dismissed_until = dismissed_until
    await db.commit()

    return {
        "dismissed": True,
        "dismissed_until": dismissed_until.isoformat(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_out(result: AutoCalibrationResult) -> AutoCalibrationOut:
    from app.engine.auto_calibration import SoilPresetMatch

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

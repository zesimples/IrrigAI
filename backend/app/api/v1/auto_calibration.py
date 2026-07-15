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
from app.models import Plot, ProbeCalibration, ProbeCalibrationRun, SectorCropProfile, SoilPreset
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
    # The bounds the engine actually USED before this run vs. what it uses now.
    # Pressing the button makes the calibration authoritative (it clears any soil
    # customization), so this reports the real CC/refill transition the user sees
    # on the chart — e.g. "CC 17→24" — not just the calibration-row delta.
    previous_fc: float | None = None
    previous_refill: float | None = None
    effective_fc: float | None = None            # m³/m³ now used by the engine
    effective_pwp: float | None = None
    effective_source: str = "probe_calibrated"   # resolve_sector_soil_bounds source
    changed: bool = True                          # effective bounds moved before→after
    applied: bool = True                          # calibration is what the engine uses
    # True when this run turned off a soil customization so the calibration could
    # take precedence (the recency rule: pressing the button overrides a manual edit).
    cleared_customization: bool = False


class CalibrationHistoryOut(BaseModel):
    id: str
    sector_id: str
    observed_fc: float
    observed_refill: float
    method: str
    num_cycles: int
    consistency: float
    window_days: int
    computed_at: datetime
    source: str
    status: str
    previous_fc: float | None = None
    previous_refill: float | None = None
    applied_at: datetime | None = None

    model_config = {"from_attributes": True}


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
    envelope (NOT an LLM) and saves it. Recency rule: pressing the button makes
    the calibration authoritative — it clears any soil customization
    (is_customized) so the calibration drives CC/refill, depletion and the
    recommendation. A later manual soil/CC-PMP edit re-sets is_customized and
    overrides the calibration again.
    """
    from app.engine.pipeline import resolve_sector_soil_bounds

    await access.sector(sector_id)

    # The bounds the engine used BEFORE this run (what the user currently sees) —
    # resolved before compute_and_save mutates the calibration row.
    before = await resolve_sector_soil_bounds(sector_id, db)

    saved = await _calib_service.compute_and_save(
        sector_id,
        db,
        source="manual",
        created_by_id=str(access.current_user.id),
    )
    if saved is None:
        # Report the actual blocker (tension-only probe, too few VWC readings,
        # implausible envelope) rather than a generic "insufficient data".
        reason = await _service.diagnose_unavailable(sector_id, db)
        raise HTTPException(422, detail=reason)

    # Recency rule: the button overrides a prior manual customization so the fresh
    # calibration takes precedence in the resolver.
    scp = (await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
    )).scalar_one_or_none()
    cleared_customization = bool(scp and scp.is_customized)
    if cleared_customization:
        scp.is_customized = False
    await db.flush()

    # autoflush makes resolve see the new calibration row + cleared customization.
    after = await resolve_sector_soil_bounds(sector_id, db)
    changed = (
        before.fc is None
        or abs(before.fc - after.fc) >= _CHANGE_EPS_M3M3
        or abs(before.pwp - after.pwp) >= _CHANGE_EPS_M3M3
    )

    await audit.log(
        "probe_calibration_computed",
        "sector",
        sector_id,
        db,
        before_data={"source": before.source, "fc": before.fc, "pwp": before.pwp},
        after_data={
            "observed_fc": saved.observed_fc,
            "observed_refill": saved.observed_refill,
            "method": saved.method,
            "effective_source": after.source,
            "effective_fc": after.fc,
            "effective_pwp": after.pwp,
            "cleared_customization": cleared_customization,
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
        previous_fc=before.fc,
        previous_refill=before.pwp,
        effective_fc=after.fc,
        effective_pwp=after.pwp,
        effective_source=after.source,
        changed=changed,
        applied=after.source == "probe_calibrated",
        cleared_customization=cleared_customization,
    )


@router.get(
    "/sectors/{sector_id}/calibration-runs",
    response_model=list[CalibrationHistoryOut],
)
async def list_calibration_runs(
    sector_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    await access.sector(sector_id)
    rows = (
        await db.execute(
            select(ProbeCalibrationRun)
            .where(ProbeCalibrationRun.sector_id == sector_id)
            .order_by(ProbeCalibrationRun.computed_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [CalibrationHistoryOut.model_validate(row) for row in rows]


@router.post(
    "/calibration-runs/{run_id}/apply",
    response_model=CalibrationHistoryOut,
)
async def apply_calibration_run(
    run_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(ProbeCalibrationRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Calibration run not found")
    await access.sector(str(run.sector_id))

    before = (await db.execute(
        select(ProbeCalibration).where(ProbeCalibration.sector_id == run.sector_id)
    )).scalar_one_or_none()
    scp = (await db.execute(
        select(SectorCropProfile).where(SectorCropProfile.sector_id == run.sector_id)
    )).scalar_one_or_none()
    if scp and scp.is_customized:
        scp.is_customized = False
    await _calib_service.apply_run(run, db)
    await audit.log(
        "probe_calibration_run_applied",
        "probe_calibration_run",
        str(run.id),
        db,
        user_id=str(access.current_user.id),
        before_data={
            "observed_fc": before.observed_fc if before else None,
            "observed_refill": before.observed_refill if before else None,
        },
        after_data={
            "observed_fc": run.observed_fc,
            "observed_refill": run.observed_refill,
        },
    )
    await db.commit()
    await db.refresh(run)
    return CalibrationHistoryOut.model_validate(run)


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

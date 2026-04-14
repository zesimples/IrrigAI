from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CropProfileTemplate, SoilPreset
from app.models.sector_crop_profile import SectorCropProfile
from app.schemas.crop_profile import (
    CropProfileTemplateOut,
    SectorCropProfileOut,
    SectorCropProfileReset,
    SectorCropProfileUpdate,
    SoilPresetOut,
)

router = APIRouter(tags=["crop-profiles"])


# ── Crop Profile Templates ────────────────────────────────────────────────────

@router.get("/crop-profile-templates", response_model=list[CropProfileTemplateOut])
async def list_crop_profile_templates(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CropProfileTemplate).order_by(CropProfileTemplate.name_en))).scalars().all()
    return [CropProfileTemplateOut.model_validate(r) for r in rows]


@router.get("/crop-profile-templates/{template_id}", response_model=CropProfileTemplateOut)
async def get_crop_profile_template(template_id: str, db: AsyncSession = Depends(get_db)):
    tpl = await db.get(CropProfileTemplate, template_id)
    if not tpl:
        raise HTTPException(404, detail="Crop profile template not found")
    return CropProfileTemplateOut.model_validate(tpl)


# ── Soil Presets ──────────────────────────────────────────────────────────────

@router.get("/soil-presets", response_model=list[SoilPresetOut])
async def list_soil_presets(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SoilPreset).order_by(SoilPreset.name_en))).scalars().all()
    return [SoilPresetOut.model_validate(r) for r in rows]


# ── Sector Crop Profile ───────────────────────────────────────────────────────

@router.get("/sectors/{sector_id}/crop-profile", response_model=SectorCropProfileOut)
async def get_sector_crop_profile(sector_id: str, db: AsyncSession = Depends(get_db)):
    profile = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
    ).scalar_one_or_none()
    if not profile:
        raise HTTPException(404, detail="Crop profile not found for this sector")
    return SectorCropProfileOut.model_validate(profile)


@router.put("/sectors/{sector_id}/crop-profile", response_model=SectorCropProfileOut)
async def update_sector_crop_profile(
    sector_id: str,
    body: SectorCropProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    profile = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
    ).scalar_one_or_none()
    if not profile:
        raise HTTPException(404, detail="Crop profile not found for this sector")

    for k, v in body.model_dump(exclude_none=True).items():
        setattr(profile, k, v)
    profile.is_customized = True

    await db.commit()
    await db.refresh(profile)
    return SectorCropProfileOut.model_validate(profile)


@router.post("/sectors/{sector_id}/crop-profile/reset", response_model=SectorCropProfileOut)
async def reset_sector_crop_profile(
    sector_id: str,
    body: SectorCropProfileReset,
    db: AsyncSession = Depends(get_db),
):
    tpl = await db.get(CropProfileTemplate, body.template_id)
    if not tpl:
        raise HTTPException(404, detail="Template not found")

    profile = (
        await db.execute(
            select(SectorCropProfile).where(SectorCropProfile.sector_id == sector_id)
        )
    ).scalar_one_or_none()

    if profile:
        profile.source_template_id = tpl.id
        profile.crop_type = tpl.crop_type
        profile.mad = tpl.mad
        profile.root_depth_mature_m = tpl.root_depth_mature_m
        profile.root_depth_young_m = tpl.root_depth_young_m
        profile.maturity_age_years = tpl.maturity_age_years
        profile.stages = tpl.stages
        profile.is_customized = False
    else:
        profile = SectorCropProfile(
            sector_id=sector_id,
            source_template_id=tpl.id,
            crop_type=tpl.crop_type,
            mad=tpl.mad,
            root_depth_mature_m=tpl.root_depth_mature_m,
            root_depth_young_m=tpl.root_depth_young_m,
            maturity_age_years=tpl.maturity_age_years,
            stages=tpl.stages,
            is_customized=False,
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)
    return SectorCropProfileOut.model_validate(profile)

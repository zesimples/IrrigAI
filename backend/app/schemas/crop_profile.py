from datetime import datetime

from pydantic import BaseModel


class CropStage(BaseModel):
    name: str
    name_pt: str | None = None
    start_doy: int
    end_doy: int
    kc: float
    description: str | None = None


class CropProfileTemplateOut(BaseModel):
    id: str
    crop_type: str
    name_pt: str
    name_en: str
    is_system_default: bool
    mad: float
    root_depth_mature_m: float
    root_depth_young_m: float
    maturity_age_years: int | None = None
    stages: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


class SoilPresetOut(BaseModel):
    id: str
    name_pt: str
    name_en: str
    texture: str
    field_capacity: float
    wilting_point: float
    taw_mm_per_m: float
    is_system_default: bool

    model_config = {"from_attributes": True}


class SectorCropProfileOut(BaseModel):
    id: str
    sector_id: str
    source_template_id: str | None = None
    crop_type: str
    mad: float
    root_depth_mature_m: float
    root_depth_young_m: float
    maturity_age_years: int | None = None
    stages: list[dict]
    is_customized: bool
    field_capacity: float | None = None
    wilting_point: float | None = None
    soil_preset_id: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectorCropProfileUpdate(BaseModel):
    mad: float | None = None
    root_depth_mature_m: float | None = None
    root_depth_young_m: float | None = None
    maturity_age_years: int | None = None
    stages: list[dict] | None = None
    field_capacity: float | None = None
    wilting_point: float | None = None
    soil_preset_id: str | None = None


class SectorCropProfileReset(BaseModel):
    template_id: str

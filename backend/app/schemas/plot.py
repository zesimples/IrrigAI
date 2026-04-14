from datetime import datetime

from pydantic import BaseModel


class PlotBase(BaseModel):
    name: str
    area_ha: float | None = None
    soil_texture: str | None = None
    field_capacity: float | None = None
    wilting_point: float | None = None
    stone_content_pct: float | None = None
    notes: str | None = None


class PlotCreate(PlotBase):
    pass


class PlotUpdate(BaseModel):
    name: str | None = None
    area_ha: float | None = None
    soil_texture: str | None = None
    field_capacity: float | None = None
    wilting_point: float | None = None
    stone_content_pct: float | None = None
    notes: str | None = None


class PlotOut(PlotBase):
    id: str
    farm_id: str
    soil_preset_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlotDetail(PlotOut):
    sector_count: int = 0

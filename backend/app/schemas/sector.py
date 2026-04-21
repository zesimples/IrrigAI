from datetime import date, datetime

from pydantic import BaseModel
from app.schemas.recommendation import StressProjectionOut


class SectorBase(BaseModel):
    name: str
    area_ha: float | None = None
    crop_type: str
    variety: str | None = None
    planting_year: int | None = None
    sowing_date: date | None = None
    tree_spacing_m: float | None = None
    row_spacing_m: float | None = None
    trees_per_ha: int | None = None
    current_phenological_stage: str | None = None
    irrigation_strategy: str = "full_etc"
    deficit_factor: float = 1.0
    rainfall_effectiveness: float = 0.8


class SectorCreate(SectorBase):
    pass


class SectorUpdate(BaseModel):
    name: str | None = None
    area_ha: float | None = None
    variety: str | None = None
    planting_year: int | None = None
    sowing_date: date | None = None
    tree_spacing_m: float | None = None
    row_spacing_m: float | None = None
    trees_per_ha: int | None = None
    current_phenological_stage: str | None = None
    irrigation_strategy: str | None = None
    deficit_factor: float | None = None
    rainfall_effectiveness: float | None = None


class IrrigationSystemOut(BaseModel):
    id: str
    system_type: str
    emitter_flow_lph: float | None = None
    emitter_spacing_m: float | None = None
    application_rate_mm_h: float | None = None
    efficiency: float
    distribution_uniformity: float = 0.90
    max_runtime_hours: float | None = None
    min_irrigation_mm: float | None = None
    max_irrigation_mm: float | None = None

    model_config = {"from_attributes": True}


class SectorOut(SectorBase):
    id: str
    plot_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectorDetail(SectorOut):
    irrigation_system: IrrigationSystemOut | None = None
    probe_count: int = 0


class ProbeHealthSummary(BaseModel):
    probe_id: str
    external_id: str
    health_status: str
    last_reading_at: datetime | None = None


class IrrigationSystemCreate(BaseModel):
    system_type: str
    emitter_flow_lph: float | None = None
    emitter_spacing_m: float | None = None
    application_rate_mm_h: float | None = None
    efficiency: float = 0.90
    distribution_uniformity: float = 0.90
    max_runtime_hours: float | None = None
    min_irrigation_mm: float | None = None
    max_irrigation_mm: float | None = None


class SectorStatus(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    current_stage: str | None = None

    # Rootzone
    swc_current: float | None = None
    swc_source: str | None = None
    depletion_pct: float | None = None   # % of TAW depleted

    # Latest recommendation summary
    latest_recommendation_id: str | None = None
    latest_action: str | None = None
    latest_confidence_score: float | None = None
    latest_confidence_level: str | None = None
    latest_irrigation_depth_mm: float | None = None
    latest_runtime_min: float | None = None
    recommendation_generated_at: datetime | None = None

    # Alerts
    active_alerts_critical: int = 0
    active_alerts_warning: int = 0
    active_alerts_info: int = 0

    # Last irrigation
    last_irrigated_at: datetime | None = None
    last_applied_mm: float | None = None

    # Probe health
    probes: list[ProbeHealthSummary] = []
    data_freshness_hours: float | None = None

    # 48-72h stress projection (from latest recommendation inputs_snapshot)
    stress_projection: StressProjectionOut | None = None

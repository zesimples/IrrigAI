# backend/app/schemas/flowmeter.py
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class FlowmeterOut(BaseModel):
    id: str
    sector_id: str
    external_device_id: int
    serial_number: str | None
    name: str
    is_active: bool
    last_reading_at: datetime | None

    model_config = {"from_attributes": True}


class FlowmeterReadingPoint(BaseModel):
    timestamp: datetime
    value: float


class FlowmeterReadingsResponse(BaseModel):
    flowmeter_id: str
    sector_name: str
    crop: str
    unit: str = "m3/ha"
    interval: str
    readings: list[FlowmeterReadingPoint]


class IrrigationEventOut(BaseModel):
    id: str
    start_time: datetime
    end_time: datetime
    duration_minutes: float
    total_m3_ha: float
    date: date

    model_config = {"from_attributes": True}


class FlowmeterEventsSummary(BaseModel):
    total_events: int
    total_m3_ha: float
    avg_m3_ha_per_event: float
    period_days: int


class FlowmeterEventsResponse(BaseModel):
    events: list[IrrigationEventOut]
    summary: FlowmeterEventsSummary


class SectorDailyBreakdown(BaseModel):
    date: date
    m3_ha: float


class FlowmeterSectorDashboard(BaseModel):
    sector_id: str
    sector_name: str
    crop: str
    has_flowmeter: bool
    total_m3_ha: float
    num_events: int
    last_irrigation: datetime | None
    last_event_m3_ha: float | None
    daily_breakdown: list[SectorDailyBreakdown]


class CropSummary(BaseModel):
    total_m3_ha: float
    num_sectors: int
    num_events: int


class FlowmeterDashboardResponse(BaseModel):
    farm_name: str
    period: str
    period_start: date
    period_end: date
    total_m3_ha: float
    sectors: list[FlowmeterSectorDashboard]
    by_crop: dict[str, CropSummary]


# ── AI Analysis schemas ──────────────────────────────────────────────────────

class FlowmeterAnalysisRequest(BaseModel):
    period_days: int = Field(default=7, ge=1, le=365)
    language: str = "pt"
    force_refresh: bool = False


class FlowmeterCropStats(BaseModel):
    total_m3_ha: float
    avg_per_sector: float
    avg_per_event: float
    num_events: int


class FlowmeterAnalysisStatistics(BaseModel):
    total_m3_ha: float
    total_events: int
    sectors_with_data: int
    sectors_without_data: int
    by_crop: dict[str, FlowmeterCropStats]
    stopped_sectors: list[str]
    top_consumers: list[str]
    trend: str
    typical_start_hour: int | None


class FlowmeterSectorStatistics(BaseModel):
    total_m3_ha: float
    num_events: int
    avg_m3_ha_per_event: float
    avg_interval_days: float | None
    pattern: str
    consistency_score: float = Field(..., ge=0.0, le=1.0)
    vs_crop_avg_pct: float | None
    typical_start_hour: int | None
    avg_duration_minutes: float | None


class FlowmeterAnalysisResponse(BaseModel):
    analysis: str
    statistics: FlowmeterAnalysisStatistics


class FlowmeterSectorAnalysisResponse(BaseModel):
    analysis: str
    statistics: FlowmeterSectorStatistics


# ── Deviation alarm schemas ───────────────────────────────────────────────────

class FlowmeterDeviationSector(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    direction: Literal["above", "below"]
    deviation_pct: float
    sector_avg_m3ha: float
    crop_avg_m3ha: float
    interior_day_count: int   # days with interior 15-min readings (first+last reading stripped per day)


class FlowmeterInsufficientDataSector(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    interior_day_count: int   # days with interior 15-min readings (first+last reading stripped per day)


class FlowmeterDeviationsResponse(BaseModel):
    period_days: int
    deviating: list[FlowmeterDeviationSector]
    insufficient_data: list[FlowmeterInsufficientDataSector]
    crop_averages: dict[str, float]   # crop_type → mean of sector interior-day averages (m³/ha/day)
    evaluated_at: datetime


# ── Flow rate reference schemas ───────────────────────────────────────────────

class FlowmeterReferenceOut(BaseModel):
    id: str
    flowmeter_id: str
    reference_rate_m3_ha: float | None
    tolerance_pct: float
    upper_limit_m3_ha: float | None
    lower_limit_m3_ha: float | None
    num_events_analyzed: int
    std_dev: float
    status: str  # "established", "provisional", "insufficient"
    computed_at: datetime
    is_manual_override: bool
    sector_id: str | None = None
    sector_name: str | None = None
    crop_type: str | None = None

    model_config = {"from_attributes": True}


class FlowmeterReferenceManualSet(BaseModel):
    reference_rate_m3_ha: float = Field(..., gt=0.0, description="Manual reference rate in m³/ha")
    tolerance_pct: float = Field(default=5.0, ge=0.5, le=50.0)

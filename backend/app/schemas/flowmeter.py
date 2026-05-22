# backend/app/schemas/flowmeter.py
from datetime import date, datetime

from pydantic import BaseModel


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

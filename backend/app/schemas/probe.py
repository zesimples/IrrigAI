from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProbeDepthOut(BaseModel):
    id: str
    depth_cm: int
    sensor_type: str
    calibration_offset: float
    calibration_factor: float

    model_config = {"from_attributes": True}


class ProbeOut(BaseModel):
    id: str
    sector_id: str
    external_id: str
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    health_status: str
    last_reading_at: datetime | None = None
    is_reference: bool

    model_config = {"from_attributes": True}


class ProbeDetail(ProbeOut):
    depths: list[ProbeDepthOut] = []


class ProbeCreate(BaseModel):
    external_id: str
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    is_reference: bool = False


class ProbeUpdate(BaseModel):
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    health_status: str | None = None
    is_reference: bool | None = None


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    vwc: float
    quality: str


class DepthReadings(BaseModel):
    depth_cm: int
    readings: list[TimeSeriesPoint]


class ReferenceLines(BaseModel):
    field_capacity: float | None = None
    wilting_point: float | None = None
    optimal_range: list[float] | None = None   # [lower, upper]


class ProbeDetectedEvent(BaseModel):
    id: str
    timestamp: datetime
    kind: Literal["irrigation", "rain", "unlogged", "unknown"]
    confidence: Literal["low", "medium", "high"]
    depths_cm: list[int]
    delta_vwc: float
    rainfall_mm: float | None = None
    irrigation_mm: float | None = None
    message: str


class ProbeReadingsResponse(BaseModel):
    probe_id: str
    depths: list[DepthReadings]
    reference_lines: ReferenceLines
    events: list[ProbeDetectedEvent] = Field(default_factory=list)

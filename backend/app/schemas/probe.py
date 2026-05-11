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
    score: float = 0.0
    probability_irrigation: float = 0.0
    probability_rain: float = 0.0
    probability_unlogged: float = 0.0
    source_match_score: float = 0.0
    depth_sequence_score: float = 0.0
    signal_strength_score: float = 0.0
    sensor_quality_score: float = 0.0
    message: str


class ProbeReadingsResponse(BaseModel):
    probe_id: str
    depths: list[DepthReadings]
    reference_lines: ReferenceLines
    events: list[ProbeDetectedEvent] = Field(default_factory=list)


class ProbeReadingGap(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: float
    expected_missing_readings: int


class ProbeDepthDiagnostics(BaseModel):
    depth_cm: int
    sensor_type: str
    unit: str | None = None
    reading_count: int
    first_reading_at: datetime | None = None
    last_reading_at: datetime | None = None
    latest_quality: str | None = None
    quality_counts: dict[str, int] = Field(default_factory=dict)
    median_interval_minutes: float | None = None
    expected_interval_minutes: float | None = None
    max_gap_minutes: float | None = None
    gap_threshold_minutes: float | None = None
    gap_count: int
    gaps: list[ProbeReadingGap] = Field(default_factory=list)
    coverage_pct: float | None = None
    freshness_hours: float | None = None
    status: Literal["ok", "partial", "stale", "no_data"]
    notes: list[str] = Field(default_factory=list)


class ProbeReadingsDiagnosticsResponse(BaseModel):
    probe_id: str
    external_id: str
    since: datetime
    until: datetime
    probe_last_reading_at: datetime | None = None
    depth_count: int
    total_readings: int
    overall_status: Literal["ok", "partial", "stale", "no_data"]
    expected_interval_minutes: float | None = None
    max_gap_minutes: float | None = None
    gap_count: int
    suggested_backfill_hours: int
    depths: list[ProbeDepthDiagnostics]

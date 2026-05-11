from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProbeDepthOut(BaseModel):
    id: str
    depth_cm: int
    sensor_type: str
    calibration_offset: float
    calibration_factor: float

    # Per-depth freshness state (added by ingestion service)
    last_reading_at: datetime | None = None
    last_quality_flag: str | None = None
    last_unit: str | None = None
    readings_count_total: int = 0
    last_gap_detected_at: datetime | None = None
    data_status: str = "unknown"

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


# ---------------------------------------------------------------------------
# Ingestion telemetry
# ---------------------------------------------------------------------------

class IngestionRunOut(BaseModel):
    id: str
    farm_id: str
    probe_id: str | None = None
    probe_external_id: str | None = None
    provider: str
    source_type: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    latency_ms: int | None = None
    requested_since: datetime | None = None
    requested_until: datetime | None = None
    provider_first_timestamp: datetime | None = None
    provider_last_timestamp: datetime | None = None
    provider_records_seen: int = 0
    provider_records_parsed: int = 0
    skipped_null: int = 0
    skipped_sentinel: int = 0
    skipped_unknown_depth: int = 0
    skipped_duplicate: int = 0
    inserted: int = 0
    flagged_invalid: int = 0
    flagged_suspect: int = 0
    error_message: str | None = None
    metadata_json: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Persisted water events
# ---------------------------------------------------------------------------

class DetectedWaterEventOut(BaseModel):
    id: str
    probe_id: str
    sector_id: str
    farm_id: str | None = None
    timestamp: datetime
    kind: Literal["irrigation", "rain", "unlogged", "unknown"]
    confidence: Literal["low", "medium", "high"]
    score: float = 0.0
    probability_irrigation: float = 0.0
    probability_rain: float = 0.0
    probability_unlogged: float = 0.0
    source_match_score: float = 0.0
    depth_sequence_score: float = 0.0
    signal_strength_score: float = 0.0
    sensor_quality_score: float = 0.0
    depths_cm: list[int] = Field(default_factory=list)
    delta_vwc: float = 0.0
    rainfall_mm: float | None = None
    irrigation_mm: float | None = None
    matched_irrigation_event_id: str | None = None
    matched_weather_observation_id: str | None = None
    status: str = "active"
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    notes: str | None = None
    message: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WaterEventConfirmBody(BaseModel):
    notes: str | None = None


# Backwards-compat alias used in places where the engine output is exposed as a dict.
AnyDict = dict[str, Any]

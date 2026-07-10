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
    # Display-only observed envelope for THIS depth (30-day percentile band from
    # its own readings) — lets the Soma chart sum real per-layer bounds. Null when
    # the depth lacks data, the band is implausible, or a manual soil override
    # (scp_override) is in force. Never feeds the engine's TAW.
    field_capacity: float | None = None
    wilting_point: float | None = None


class ReferenceLines(BaseModel):
    field_capacity: float | None = None
    wilting_point: float | None = None
    optimal_range: list[float] | None = None   # [lower, upper]


class ProbeDetectedEvent(BaseModel):
    id: str
    timestamp: datetime
    kind: Literal["irrigation", "rain", "unlogged", "unknown"]
    confidence: Literal["low", "medium", "high"]
    status: Literal["active", "confirmed", "rejected"] = "active"
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
    rootzone_swc: list[TimeSeriesPoint] = Field(default_factory=list)
    root_depth_cm: float | None = None


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
    kind: Literal["irrigation", "rain", "unlogged", "unknown"] | None = None


AnyDict = dict[str, Any]

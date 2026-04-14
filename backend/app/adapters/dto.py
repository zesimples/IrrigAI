"""Normalized Data Transfer Objects — the contract between adapters and the system.

Any probe or weather provider, real or mock, must map its vendor format
to these DTOs. The rest of the system (engine, ingestion, anomaly detection)
only ever sees these types.
"""

from datetime import date, datetime

from pydantic import BaseModel, field_validator


class ProbeReadingDTO(BaseModel):
    probe_external_id: str
    depth_cm: int
    timestamp: datetime           # Must be timezone-aware
    raw_value: float
    calibrated_value: float | None = None
    unit: str                     # "vwc_m3m3", "raw_counts", "celsius", "dS_m"
    sensor_type: str              # "moisture", "temperature", "ec"

    @field_validator("timestamp")
    @classmethod
    def must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ProbeReadingDTO.timestamp must be timezone-aware")
        return v


class ProbeMetadataDTO(BaseModel):
    external_id: str
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    depths_cm: list[int]
    last_reading_at: datetime | None = None
    battery_level_pct: float | None = None
    status: str = "ok"


class WeatherObservationDTO(BaseModel):
    timestamp: datetime
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    temperature_mean_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    solar_radiation_mjm2: float | None = None
    rainfall_mm: float | None = None
    et0_mm: float | None = None

    @field_validator("timestamp")
    @classmethod
    def must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("WeatherObservationDTO.timestamp must be timezone-aware")
        return v


class WeatherForecastDTO(BaseModel):
    forecast_date: date
    issued_at: datetime
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    rainfall_mm: float | None = None
    rainfall_probability_pct: float | None = None
    et0_mm: float | None = None

    @field_validator("issued_at")
    @classmethod
    def must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("WeatherForecastDTO.issued_at must be timezone-aware")
        return v


class IngestionSummary(BaseModel):
    """Returned by ingestion service after a run."""
    probe_external_id: str | None = None
    inserted: int = 0
    skipped_duplicate: int = 0
    flagged_invalid: int = 0
    flagged_suspect: int = 0
    errors: int = 0

"""Engine data classes.

All agronomic inputs come from user-configured DB records — never hardcoded.
`defaults_used` and `missing_config` track what was configured vs. inferred.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID


@dataclass
class SectorContext:
    """All inputs the engine needs for one sector. Built from DB records."""

    sector_id: str
    sector_name: str
    crop_type: str
    phenological_stage: str | None       # From Sector.current_phenological_stage
    planting_year: int | None
    tree_age_years: int | None

    # From Plot (user-configured soil)
    soil_texture: str | None
    field_capacity: float | None         # m³/m³
    wilting_point: float | None

    # From SectorCropProfile (editable copy of template)
    kc: float                            # Looked up by current stage
    kc_source: str                       # How Kc was resolved (for logging)
    mad: float
    root_depth_m: float                  # Adjusted for tree age
    rdi_eligible: bool
    rdi_factor: float | None

    # From IrrigationSystem (user-configured)
    irrigation_system_type: str | None
    application_rate_mm_h: float | None  # None if system not configured
    irrigation_efficiency: float
    distribution_uniformity: float       # 0–1, how evenly water is applied (default 0.90)
    emitter_flow_lph: float | None
    emitter_spacing_m: float | None
    row_spacing_m: float | None
    max_runtime_hours: float | None
    min_irrigation_mm: float | None
    max_irrigation_mm: float | None

    # From Sector (user-configured strategy)
    irrigation_strategy: str
    deficit_factor: float
    area_ha: float | None
    rainfall_effectiveness: float

    # Provenance tracking
    defaults_used: list[str] = field(default_factory=list)
    missing_config: list[str] = field(default_factory=list)


@dataclass
class TimestampedReading:
    timestamp: datetime
    value: float
    quality_flag: str = "ok"


@dataclass
class DepthStatus:
    depth_cm: int
    readings: list[TimestampedReading]
    latest_vwc: float | None
    hours_since_last: float | None
    quality: str = "ok"         # "ok", "stale", "missing", "suspect"


@dataclass
class RootzoneStatus:
    """Weighted rootzone SWC from probe readings."""
    swc_current: float | None           # m³/m³, weighted average
    swc_source: str                     # "probe_weighted", "water_balance", "default"
    depth_statuses: list[DepthStatus]
    has_data: bool
    hours_since_any_reading: float | None
    all_depths_ok: bool


@dataclass
class ProbeSnapshot:
    sector_id: str
    probe_ids: list[str]
    rootzone: RootzoneStatus
    anomalies_detected: list[str]       # anomaly descriptions
    is_calibrated: bool = True


@dataclass
class DailyWeather:
    date: date
    t_max: float | None = None
    t_min: float | None = None
    t_mean: float | None = None
    humidity_pct: float | None = None
    wind_ms: float | None = None
    solar_mjm2: float | None = None
    rainfall_mm: float = 0.0
    rainfall_probability_pct: float | None = None
    et0_mm: float | None = None


@dataclass
class WeatherContext:
    farm_id: str
    lat: float | None
    lon: float | None
    elevation_m: float                   # metres above sea level (default 0)
    today: DailyWeather
    forecast: list[DailyWeather]         # next N days
    hours_since_observation: float | None
    has_forecast: bool


@dataclass
class IrrigationEventSummary:
    event_id: str
    start_time: datetime
    applied_mm: float


@dataclass
class RecentIrrigationContext:
    sector_id: str
    events_7d: list[IrrigationEventSummary]
    last_irrigation_at: datetime | None
    total_applied_7d_mm: float
    has_log: bool


@dataclass
class ReasonEntry:
    order: int
    category: str           # "water_balance", "forecast", "confidence", "config"
    message_pt: str
    message_en: str
    data_key: str | None = None
    data_value: str | None = None


@dataclass
class ConfidenceResult:
    score: float            # 0.0–1.0
    level: str              # "high", "medium", "low"
    penalties: list[tuple[str, float]]   # (reason, penalty_amount)
    warnings: list[str]


@dataclass
class EngineRecommendation:
    sector_id: str
    target_date: date
    generated_at: datetime

    # Core output
    action: str                          # "irrigate", "skip", "defer"
    irrigation_depth_mm: float | None
    irrigation_runtime_min: float | None  # None if system not configured
    suggested_start_time: str | None     # "06:00"

    # Explainability
    confidence: ConfidenceResult
    reasons: list[ReasonEntry]

    # Inputs used
    et0_mm: float | None
    etc_mm: float | None
    swc_current: float | None
    depletion_mm: float | None
    raw_mm: float | None
    taw_mm: float | None
    rain_effective_mm: float
    forecast_rain_next_48h: float

    # Provenance
    defaults_used: list[str]
    missing_config: list[str]
    engine_version: str = "0.1.0"

    # Full computation log (stored as JSONB)
    computation_log: dict = field(default_factory=dict)

    # 48-72h stress projection (optional, stored in inputs_snapshot)
    stress_projection: dict | None = None

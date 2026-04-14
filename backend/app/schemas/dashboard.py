from datetime import date, datetime

from pydantic import BaseModel


class WeatherToday(BaseModel):
    et0_mm: float | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    rainfall_mm: float | None = None
    forecast_rain_next_48h_mm: float = 0.0
    forecast_rain_probability: float | None = None


class SectorSummary(BaseModel):
    sector_id: str
    sector_name: str
    crop_type: str
    current_stage: str | None = None
    action: str | None = None
    irrigation_depth_mm: float | None = None
    runtime_min: float | None = None
    confidence_level: str | None = None
    confidence_score: float | None = None
    rootzone_status: str | None = None    # "dry", "optimal", "wet", "saturated", "unknown"
    active_alerts: int = 0
    probe_health: str = "unknown"        # "ok", "warning", "error", "no_probes"
    last_irrigated: date | None = None
    last_irrigated_mm: float | None = None
    recommendation_generated_at: datetime | None = None


class AlertCounts(BaseModel):
    critical: int = 0
    warning: int = 0
    info: int = 0


class FarmOut(BaseModel):
    id: str
    name: str
    region: str | None = None


class DashboardResponse(BaseModel):
    farm: FarmOut
    date: date
    weather_today: WeatherToday
    sectors_summary: list[SectorSummary]
    active_alerts_count: AlertCounts
    missing_data_prompts: list[str]

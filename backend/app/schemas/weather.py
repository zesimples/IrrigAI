from datetime import date, datetime

from pydantic import BaseModel


class WeatherObservationOut(BaseModel):
    id: str
    farm_id: str
    timestamp: datetime
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    temperature_mean_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    solar_radiation_mjm2: float | None = None
    rainfall_mm: float | None = None
    et0_mm: float | None = None

    model_config = {"from_attributes": True}


class WeatherForecastOut(BaseModel):
    id: str
    farm_id: str
    forecast_date: date
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    humidity_pct: float | None = None
    wind_speed_ms: float | None = None
    rainfall_mm: float | None = None
    rainfall_probability_pct: float | None = None
    et0_mm: float | None = None

    model_config = {"from_attributes": True}


class Et0Point(BaseModel):
    date: date
    et0_mm: float | None


class Et0Response(BaseModel):
    farm_id: str
    points: list[Et0Point]

"""Mock weather data provider.

Generates realistic weather observations and forecasts for testing.
Parameterizable for season, latitude, and rain events.

ET0 is computed via the Hargreaves-Samani method using generated temperature
data and extraterrestrial radiation from the configured latitude.
"""

import math
import random
from datetime import UTC, date, datetime, timedelta

from app.adapters.base import WeatherDataProvider
from app.adapters.dto import WeatherForecastDTO, WeatherObservationDTO

# Season presets: (t_max_mean, t_max_std, t_min_mean, t_min_std, humidity_mean, wind_mean, solar_mean)
_SEASON_PARAMS: dict[str, dict] = {
    "summer":  {"tmax": 36, "tmax_std": 2.5, "tmin": 20, "tmin_std": 2.0,
                "rh": 28, "rh_std": 6, "wind": 3.5, "wind_std": 0.8,
                "rain_days": 0, "solar": 25},
    "spring":  {"tmax": 22, "tmax_std": 3.0, "tmin": 10, "tmin_std": 2.5,
                "rh": 60, "rh_std": 10, "wind": 3.0, "wind_std": 1.0,
                "rain_days": 2, "solar": 18},
    "autumn":  {"tmax": 25, "tmax_std": 3.5, "tmin": 12, "tmin_std": 2.5,
                "rh": 55, "rh_std": 12, "wind": 3.5, "wind_std": 1.2,
                "rain_days": 2, "solar": 16},
    "winter":  {"tmax": 14, "tmax_std": 3.0, "tmin":  4, "tmin_std": 2.0,
                "rh": 75, "rh_std": 12, "wind": 4.0, "wind_std": 1.5,
                "rain_days": 4, "solar": 10},
}


def _extraterrestrial_radiation(lat_deg: float, day_of_year: int) -> float:
    """Extraterrestrial radiation Ra (MJ/m²/day) — FAO-56 eq. 21."""
    lat = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    sd = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(-math.tan(lat) * math.tan(sd))
    ra = (24 * 60 / math.pi) * 0.082 * dr * (
        ws * math.sin(lat) * math.sin(sd)
        + math.cos(lat) * math.cos(sd) * math.sin(ws)
    )
    return round(max(0.0, ra), 2)


def _hargreaves_et0(t_max: float, t_min: float, ra: float) -> float:
    """Hargreaves-Samani ET0 (mm/day)."""
    t_mean = (t_max + t_min) / 2
    et0 = 0.0023 * (t_mean + 17.8) * ((t_max - t_min) ** 0.5) * ra
    return round(max(0.0, et0), 2)


class MockWeatherProvider(WeatherDataProvider):
    """Generates realistic weather data for a configurable season and location."""

    def __init__(
        self,
        latitude: float = 38.57,
        season: str = "summer",
        include_rain_event: bool = True,
        seed: int | None = None,
    ) -> None:
        self.latitude = latitude
        self.season = season
        self.include_rain_event = include_rain_event
        self._rng = random.Random(seed)
        self._params = _SEASON_PARAMS.get(season, _SEASON_PARAMS["summer"])

    # ------------------------------------------------------------------
    # WeatherDataProvider interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """No-op for mock."""

    async def health_check(self) -> bool:
        return True

    async def fetch_et0(self, lat: float, lon: float, for_date: date) -> float | None:
        """Return a pre-computed mock ET0 for the date."""
        doy = for_date.timetuple().tm_yday
        ra = _extraterrestrial_radiation(lat, doy)
        p = self._params
        t_max = p["tmax"] + self._rng.gauss(0, p["tmax_std"])
        t_min = p["tmin"] + self._rng.gauss(0, p["tmin_std"])
        return _hargreaves_et0(t_max, t_min, ra)

    async def fetch_observations(
        self,
        lat: float,
        lon: float,
        since: datetime,
        until: datetime,
    ) -> list[WeatherObservationDTO]:
        observations = []
        p = self._params
        rng = self._rng
        current_day = since.date()
        end_day = until.date()

        while current_day <= end_day:
            doy = current_day.timetuple().tm_yday
            ra = _extraterrestrial_radiation(lat, doy)
            t_max = round(p["tmax"] + rng.gauss(0, p["tmax_std"]), 1)
            t_min = round(p["tmin"] + rng.gauss(0, p["tmin_std"]), 1)
            t_mean = round((t_max + t_min) / 2, 1)
            humidity = round(max(5.0, p["rh"] + rng.gauss(0, p["rh_std"])), 1)
            wind = round(max(0.3, p["wind"] + rng.gauss(0, p["wind_std"])), 1)
            solar = round(max(2.0, p["solar"] + rng.gauss(0, 2.0)), 1)
            rain = 0.0
            if self.season in ("spring", "autumn", "winter") and rng.random() < p["rain_days"] / 7:
                rain = round(rng.uniform(3.0, 25.0), 1)
            et0 = _hargreaves_et0(t_max, t_min, ra)

            ts = datetime(current_day.year, current_day.month, current_day.day, 12, 0, 0, tzinfo=UTC)
            observations.append(
                WeatherObservationDTO(
                    timestamp=ts,
                    temperature_max_c=t_max,
                    temperature_min_c=t_min,
                    temperature_mean_c=t_mean,
                    humidity_pct=humidity,
                    wind_speed_ms=wind,
                    solar_radiation_mjm2=solar,
                    rainfall_mm=rain,
                    et0_mm=et0,
                )
            )
            current_day += timedelta(days=1)

        return observations

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 5,
    ) -> list[WeatherForecastDTO]:
        forecasts = []
        p = self._params
        rng = self._rng
        now = datetime.now(UTC)

        for d in range(1, days + 1):
            fc_date = (now + timedelta(days=d)).date()
            doy = fc_date.timetuple().tm_yday
            ra = _extraterrestrial_radiation(lat, doy)
            t_max = round(p["tmax"] + rng.gauss(0, p["tmax_std"] * 1.2), 1)
            t_min = round(p["tmin"] + rng.gauss(0, p["tmin_std"] * 1.2), 1)
            humidity = round(max(5.0, p["rh"] + rng.gauss(0, p["rh_std"])), 1)
            wind = round(max(0.3, p["wind"] + rng.gauss(0, p["wind_std"])), 1)
            et0 = _hargreaves_et0(t_max, t_min, ra)

            # Optional rain event on day 3 of forecast (tests rain-skip logic)
            rain_mm = 0.0
            rain_prob = 5.0
            if self.include_rain_event and d == 3:
                rain_mm = round(rng.uniform(10.0, 30.0), 1)
                rain_prob = round(rng.uniform(60.0, 90.0), 1)

            forecasts.append(
                WeatherForecastDTO(
                    forecast_date=fc_date,
                    issued_at=now,
                    temperature_max_c=t_max,
                    temperature_min_c=t_min,
                    humidity_pct=humidity,
                    wind_speed_ms=wind,
                    rainfall_mm=rain_mm,
                    rainfall_probability_pct=rain_prob,
                    et0_mm=et0,
                )
            )

        return forecasts

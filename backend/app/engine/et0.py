"""ET0 computation — Penman-Monteith (FAO-56) with Hargreaves fallback.

Uses weather data from WeatherContext. Latitude and elevation come from the
farm record (user-configured).

Elevation affects:
  - Atmospheric pressure → psychrometric constant γ
  - Clear-sky radiation Rso (turbidity correction term 2×10⁻⁵ × z)

Falls back to Hargreaves when solar or wind data is missing.
"""

import math
from datetime import date

from app.engine.types import DailyWeather


def _day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def _extraterrestrial_radiation(lat_deg: float, doy: int) -> float:
    """Ra (MJ/m²/day) — FAO-56 eq. 21."""
    lat = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    sd = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(lat) * math.tan(sd))))
    ra = (24 * 60 / math.pi) * 0.082 * dr * (
        ws * math.sin(lat) * math.sin(sd)
        + math.cos(lat) * math.cos(sd) * math.sin(ws)
    )
    return max(0.0, ra)


def penman_monteith(w: DailyWeather, lat_deg: float, elevation_m: float = 0.0) -> float | None:
    """FAO-56 Penman-Monteith ET0 (mm/day).

    Returns None if critical inputs are missing.
    Requires: t_max, t_min, t_mean, humidity_pct, wind_ms, solar_mjm2.

    elevation_m is used to correct atmospheric pressure and hence the
    psychrometric constant (γ) and clear-sky radiation (Rso) — FAO-56 eqs
    7, 8, and 37.
    """
    if any(v is None for v in [w.t_max, w.t_min, w.t_mean, w.humidity_pct, w.wind_ms, w.solar_mjm2]):
        return None

    T = w.t_mean
    Tmax, Tmin = w.t_max, w.t_min
    RH = w.humidity_pct
    u2 = w.wind_ms
    Rs = w.solar_mjm2

    doy = _day_of_year(w.date)

    # Atmospheric pressure at elevation (kPa) — FAO-56 eq. 7
    pressure_kpa = 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26

    # Psychrometric constant γ (kPa/°C) — FAO-56 eq. 8
    gamma = 0.000665 * pressure_kpa

    # Slope of saturation vapour pressure curve (kPa/°C)
    delta = (4098 * (0.6108 * math.exp(17.27 * T / (T + 237.3)))) / ((T + 237.3) ** 2)

    # Saturation vapour pressure (kPa)
    es = (0.6108 * math.exp(17.27 * Tmax / (Tmax + 237.3)) +
          0.6108 * math.exp(17.27 * Tmin / (Tmin + 237.3))) / 2
    ea = es * RH / 100.0

    # Net radiation
    Ra = _extraterrestrial_radiation(lat_deg, doy)
    Rso = (0.75 + 2e-5 * elevation_m) * Ra      # FAO-56 eq. 37
    Rns = (1 - 0.23) * Rs                        # net shortwave
    sigma = 4.903e-9
    Rnl = sigma * ((Tmax + 273.16) ** 4 + (Tmin + 273.16) ** 4) / 2 * (
        0.34 - 0.14 * math.sqrt(max(0.0, ea))
    ) * (1.35 * Rs / Rso - 0.35)
    Rn = Rns - Rnl
    G = 0.0  # daily soil heat flux ≈ 0

    et0 = (
        0.408 * delta * (Rn - G)
        + gamma * (900 / (T + 273)) * u2 * (es - ea)
    ) / (delta + gamma * (1 + 0.34 * u2))

    return round(max(0.0, et0), 3)


def hargreaves(w: DailyWeather, lat_deg: float) -> float | None:
    """Hargreaves-Samani ET0 fallback (mm/day).

    Requires: t_max, t_min. Less accurate but works with minimal data.
    Elevation does not affect Hargreaves (temperature-only method).
    """
    if w.t_max is None or w.t_min is None:
        return None

    t_mean = (w.t_max + w.t_min) / 2
    doy = _day_of_year(w.date)
    Ra = _extraterrestrial_radiation(lat_deg, doy)
    et0 = 0.0023 * (t_mean + 17.8) * math.sqrt(abs(w.t_max - w.t_min)) * Ra
    return round(max(0.0, et0), 3)


def compute_et0(w: DailyWeather, lat_deg: float, elevation_m: float = 0.0) -> tuple[float | None, str]:
    """Try Penman-Monteith; fall back to Hargreaves.

    Returns (et0_mm, method_used).
    elevation_m is passed to Penman-Monteith for pressure/Rso correction.
    """
    # Use pre-computed value if available (e.g., from weather provider)
    if w.et0_mm is not None:
        return w.et0_mm, "provider"

    pm = penman_monteith(w, lat_deg, elevation_m)
    if pm is not None:
        return pm, "penman_monteith"

    hg = hargreaves(w, lat_deg)
    if hg is not None:
        return hg, "hargreaves"

    return None, "unavailable"

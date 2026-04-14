"""Unit tests for ET0 computation (Penman-Monteith and Hargreaves)."""

from datetime import date

from app.engine.et0 import compute_et0, hargreaves, penman_monteith
from app.engine.types import DailyWeather


class TestPenmanMonteith:
    def test_typical_summer_day(self):
        """Full PM inputs → ET0 in reasonable range for warm dry day."""
        w = DailyWeather(
            date=date(2024, 7, 1),
            t_max=32.0, t_min=18.0, t_mean=25.0,
            humidity_pct=40.0, wind_ms=2.5, solar_mjm2=22.0,
        )
        et0 = penman_monteith(w, lat_deg=38.57)
        assert et0 is not None
        assert 5.0 <= et0 <= 10.0, f"Unexpected ET0={et0}"

    def test_cool_humid_day_lower_et0(self):
        w = DailyWeather(
            date=date(2024, 4, 1),
            t_max=20.0, t_min=12.0, t_mean=16.0,
            humidity_pct=80.0, wind_ms=1.0, solar_mjm2=10.0,
        )
        et0 = penman_monteith(w, lat_deg=38.57)
        assert et0 is not None
        assert 1.0 <= et0 <= 5.0, f"Unexpected ET0={et0}"

    def test_returns_none_when_missing_inputs(self):
        """Missing t_mean → None."""
        w = DailyWeather(
            date=date(2024, 7, 1),
            t_max=32.0, t_min=18.0,
            humidity_pct=40.0, wind_ms=2.5, solar_mjm2=22.0,
        )
        assert penman_monteith(w, lat_deg=38.57) is None

    def test_returns_float(self):
        w = DailyWeather(
            date=date(2024, 6, 15),
            t_max=28.0, t_min=16.0, t_mean=22.0,
            humidity_pct=55.0, wind_ms=2.0, solar_mjm2=18.0,
        )
        et0 = penman_monteith(w, lat_deg=38.57)
        assert isinstance(et0, float)
        assert et0 > 0


class TestHargreaves:
    def test_typical_values(self):
        w = DailyWeather(date=date(2024, 7, 1), t_max=30.0, t_min=16.0)
        et0 = hargreaves(w, lat_deg=38.57)
        assert et0 is not None
        assert 4.0 <= et0 <= 20.0, f"ET0={et0} out of range"

    def test_equal_tmax_tmin_returns_zero(self):
        """t_max == t_min → sqrt of 0 → ET0 = 0."""
        w = DailyWeather(date=date(2024, 6, 1), t_max=20.0, t_min=20.0)
        et0 = hargreaves(w, lat_deg=38.57)
        assert et0 == 0.0

    def test_returns_none_when_no_temp(self):
        w = DailyWeather(date=date(2024, 6, 1))
        assert hargreaves(w, lat_deg=40.0) is None

    def test_returns_float(self):
        w = DailyWeather(date=date(2024, 7, 15), t_max=25.0, t_min=12.0)
        et0 = hargreaves(w, lat_deg=40.0)
        assert isinstance(et0, float)


class TestComputeEt0:
    def test_uses_pm_when_full_data(self):
        """All PM inputs present → uses penman_monteith."""
        w = DailyWeather(
            date=date(2024, 7, 1),
            t_max=34.0, t_min=20.0, t_mean=27.0,
            humidity_pct=45.0, wind_ms=2.0, solar_mjm2=22.0,
        )
        val, method = compute_et0(w, lat_deg=38.57)
        assert val is not None
        assert method == "penman_monteith"
        assert 4.0 <= val <= 12.0

    def test_falls_back_to_hargreaves_when_incomplete(self):
        """Missing humidity/wind/solar → falls back to hargreaves."""
        w = DailyWeather(date=date(2024, 7, 1), t_max=34.0, t_min=20.0)
        val, method = compute_et0(w, lat_deg=38.57)
        assert val is not None
        assert method == "hargreaves"

    def test_returns_unavailable_when_no_temp(self):
        w = DailyWeather(date=date(2024, 7, 1))
        val, method = compute_et0(w, lat_deg=38.57)
        assert val is None
        assert method == "unavailable"

    def test_uses_stored_et0_when_provided(self):
        """Pre-computed et0_mm → returns it directly without recalculating."""
        w = DailyWeather(date=date(2024, 7, 1), t_max=34.0, t_min=20.0, et0_mm=6.5)
        val, method = compute_et0(w, lat_deg=38.57)
        assert val == 6.5
        assert method == "provider"

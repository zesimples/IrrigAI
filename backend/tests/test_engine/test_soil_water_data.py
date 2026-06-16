from datetime import date

from app.engine.soil_water_data import _assemble_daily, _find_window_start


def test_find_window_start_uses_last_recharge():
    weather = {date(2026, 3, 18): (3.0, 1.0), date(2026, 3, 19): (3.0, 40.0),
               date(2026, 6, 1): (6.0, 0.0)}
    start = _find_window_start(weather, today=date(2026, 6, 16),
                               max_lookback_days=365, recharge_mm=20.0)
    assert start == date(2026, 3, 19)


def test_find_window_start_caps_when_no_recharge():
    weather = {date(2026, 6, 1): (6.0, 0.0)}
    today = date(2026, 6, 16)
    start = _find_window_start(weather, today=today, max_lookback_days=365, recharge_mm=20.0)
    assert start == date(2025, 6, 16)


def test_assemble_marks_offline_meter_day():
    start, today = date(2026, 6, 1), date(2026, 6, 2)
    weather = {date(2026, 6, 1): (6.0, 0.0), date(2026, 6, 2): (6.0, 0.0)}
    irrigation_mm_by_day = {}
    reading_dates = {date(2026, 6, 1)}
    days = _assemble_daily(start, today, weather, irrigation_mm_by_day, reading_dates)
    assert days[0].irrigation_unmeasured is False
    assert days[1].irrigation_unmeasured is True


def test_assemble_marks_weather_gap_and_passes_irrigation():
    start, today = date(2026, 6, 1), date(2026, 6, 2)
    weather = {date(2026, 6, 1): (6.0, 0.0)}
    irrigation_mm_by_day = {date(2026, 6, 1): 4.5}
    reading_dates = {date(2026, 6, 1), date(2026, 6, 2)}
    days = _assemble_daily(start, today, weather, irrigation_mm_by_day, reading_dates)
    assert days[0].irrigation_mm == 4.5
    assert days[0].weather_gap is False
    assert days[1].weather_gap is True
    assert days[1].et0_mm is None

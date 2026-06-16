from datetime import date

import pytest

from app.engine.soil_water_model import DayInput, model_soil_water

# clay-loam-ish: fc=0.30, pwp=0.15, root=0.5m → TAW = (0.30-0.15)*0.5*1000 = 75 mm
_SOIL = dict(fc=0.30, pwp=0.15, root_depth_m=0.5, kc=0.6,
             rainfall_effectiveness=0.8, application_efficiency=0.9)


def _days(start: date, n: int, *, et0, rain=0.0, irr=0.0, **kw):
    return [DayInput(day=date.fromordinal(start.toordinal() + i),
                     et0_mm=et0, rain_mm=rain, irrigation_mm=irr, **kw) for i in range(n)]


def test_zero_root_depth_raises():
    daily = _days(date(2026, 7, 1), 3, et0=5.0)
    with pytest.raises(ValueError, match="root_depth_m"):
        model_soil_water(daily=daily, today=date(2026, 7, 3),
                         **{**_SOIL, "root_depth_m": 0.0})


def test_big_rain_anchors_to_field_capacity():
    today = date(2026, 3, 20)
    daily = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.swc_current == 0.30
    assert r.depletion_mm == 0.0
    assert r.seed_kind == "rain_anchored"
    assert r.last_anchor_date == date(2026, 3, 19)


def test_dry_days_after_anchor_deplete_by_et():
    today = date(2026, 3, 30)
    daily = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    daily += _days(date(2026, 3, 20), 10, et0=5.0)
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert 28.0 <= r.depletion_mm <= 32.0
    assert r.days_since_anchor == 11
    assert r.confidence_factor >= 0.5


def test_measured_irrigation_reduces_depletion():
    today = date(2026, 3, 30)
    base = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    dry = _days(date(2026, 3, 20), 10, et0=5.0)
    irr = _days(date(2026, 3, 20), 10, et0=5.0, irr=3.0)
    r_dry = model_soil_water(daily=base + dry, today=today, **_SOIL)
    r_irr = model_soil_water(daily=base + irr, today=today, **_SOIL)
    assert r_irr.depletion_mm < r_dry.depletion_mm


def test_no_anchor_falls_back_to_static_seed():
    today = date(2026, 8, 1)
    daily = _days(date(2026, 7, 22), 10, et0=6.0)
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.seed_kind == "static_fallback"
    assert r.last_anchor_date is None
    assert r.days_since_anchor is None


def test_weather_gap_carries_forward_et0_and_counts_gap():
    today = date(2026, 7, 5)
    daily = [DayInput(day=date(2026, 7, 1), et0_mm=6.0, rain_mm=0.0, irrigation_mm=0.0)]
    daily.append(DayInput(day=date(2026, 7, 2), et0_mm=None, rain_mm=0.0,
                          irrigation_mm=0.0, weather_gap=True))
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.n_gap_days == 1


def test_offline_meter_day_is_a_gap_not_zero_assumption():
    today = date(2026, 7, 5)
    daily = [DayInput(day=date(2026, 7, 1), et0_mm=6.0, rain_mm=0.0,
                      irrigation_mm=0.0, irrigation_unmeasured=True)]
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.n_gap_days == 1


def test_confidence_holds_medium_through_long_dry_spell_when_no_gaps():
    today = date(2026, 11, 1)
    daily = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    daily += _days(date(2026, 3, 20), 226, et0=5.0, irr=3.0)
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.days_since_anchor and r.days_since_anchor > 200
    assert r.confidence_factor >= 0.5


def test_deterministic():
    today = date(2026, 4, 1)
    daily = _days(date(2026, 3, 20), 12, et0=5.0, irr=2.0)
    a = model_soil_water(daily=daily, today=today, **_SOIL)
    b = model_soil_water(daily=daily, today=today, **_SOIL)
    assert a == b

"""Assemble per-day soil-water model inputs from weather + flowmeter history.

Pure helpers (_find_window_start, _assemble_daily) are unit-tested; load_daily_inputs is a
thin async wrapper that queries the DB and delegates to them.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.soil_water_model import DayInput
from app.models import FlowmeterReading, IrrigationEventDetected, WeatherObservation

MAX_LOOKBACK_DAYS = 365
RECHARGE_RAIN_MM = 20.0


def _find_window_start(
    weather_by_day: dict[date, tuple[float | None, float]],
    today: date,
    max_lookback_days: int,
    recharge_mm: float,
) -> date:
    """Most recent day (within max_lookback) whose rain >= recharge_mm; else the cap."""
    floor = today - timedelta(days=max_lookback_days)
    recharge_days = [d for d, (_et0, rain) in weather_by_day.items()
                     if d >= floor and rain >= recharge_mm]
    return max(recharge_days) if recharge_days else floor


def _assemble_daily(
    window_start: date,
    today: date,
    weather_by_day: dict[date, tuple[float | None, float]],
    irrigation_mm_by_day: dict[date, float],
    reading_dates: set[date],
) -> list[DayInput]:
    days: list[DayInput] = []
    cur = window_start
    while cur <= today:
        et0, rain = weather_by_day.get(cur, (None, 0.0))
        weather_gap = cur not in weather_by_day
        irrigation_mm = irrigation_mm_by_day.get(cur, 0.0)
        irrigation_unmeasured = cur not in reading_dates
        days.append(DayInput(
            day=cur,
            et0_mm=et0,
            rain_mm=rain,
            irrigation_mm=irrigation_mm,
            weather_gap=weather_gap,
            irrigation_unmeasured=irrigation_unmeasured,
        ))
        cur += timedelta(days=1)
    return days


def _start_of_day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


async def load_daily_inputs(
    *,
    sector_id: str,
    farm_id: str,
    flowmeter_id: str,
    today: date,
    db: AsyncSession,
) -> list[DayInput]:
    """Assemble the daily soil-water inputs for one flowmeter-backed sector.

    `today` must be a UTC-based date — all stored timestamps are UTC-aware and reduced
    to a date via `.date()`, so a non-UTC `today` could drift the window by a day.
    Note the query ordering matters: weather is loaded first because `window_start`
    is derived from it, and the irrigation/reading queries depend on `window_start`.
    """
    floor = today - timedelta(days=MAX_LOOKBACK_DAYS)

    # Weather: aggregate observations to one (et0, rain) per day (max et0, summed rain).
    # Column-level select — only these three fields are needed (the model has many more).
    weather_by_day: dict[date, tuple[float | None, float]] = {}
    obs = (await db.execute(
        select(WeatherObservation.timestamp, WeatherObservation.et0_mm,
               WeatherObservation.rainfall_mm)
        .where(WeatherObservation.farm_id == farm_id,
               WeatherObservation.timestamp >= _start_of_day(floor))
    )).all()
    for ts, et0_mm, rainfall_mm in obs:
        d = ts.date()
        et0_prev, rain_prev = weather_by_day.get(d, (None, 0.0))
        if et0_mm is None:
            et0 = et0_prev
        elif et0_prev is None:
            et0 = et0_mm
        else:
            et0 = max(et0_prev, et0_mm)
        weather_by_day[d] = (et0, rain_prev + (rainfall_mm or 0.0))

    # window_start is derived from the weather above — keep this after the weather query.
    window_start = _find_window_start(weather_by_day, today, MAX_LOOKBACK_DAYS, RECHARGE_RAIN_MM)

    # Irrigation applied per day (m3/ha -> mm). Column-level select (model has many more).
    irrigation_mm_by_day: dict[date, float] = {}
    events = (await db.execute(
        select(IrrigationEventDetected.date, IrrigationEventDetected.total_m3_ha)
        .where(IrrigationEventDetected.sector_id == sector_id,
               IrrigationEventDetected.date >= window_start)
    )).all()
    for ev_date, total_m3_ha in events:
        irrigation_mm_by_day[ev_date] = irrigation_mm_by_day.get(ev_date, 0.0) + (total_m3_ha / 10.0)

    # Days the meter actually reported (offline vs genuinely-no-irrigation).
    reading_rows = (await db.execute(
        select(FlowmeterReading.timestamp)
        .where(FlowmeterReading.flowmeter_id == flowmeter_id,
               FlowmeterReading.timestamp >= _start_of_day(window_start))
    )).scalars().all()
    reading_dates = {ts.date() for ts in reading_rows}

    return _assemble_daily(window_start, today, weather_by_day, irrigation_mm_by_day, reading_dates)

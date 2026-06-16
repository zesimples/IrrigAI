# Soil-Water Balance Model (probe-less flowmeter sectors) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static 70%-of-TAW seed with a rain-anchored FAO-56 running water balance for probe-less sectors that have a flowmeter, reconstructed statelessly each run from weather + flowmeter history.

**Architecture:** A pure math module (`soil_water_model.py`) integrates a daily balance forward from the last field-capacity recharge, crediting measured irrigation + rain in and ET₀×Kc out. A thin async loader (`soil_water_data.py`) assembles the daily inputs from `WeatherObservation`, `IrrigationEventDetected`, and `FlowmeterReading`. The pipeline calls them only when there is no probe SWC and an active flowmeter exists; probes stay authoritative. Confidence reflects input completeness, not days-since-rain.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, pytest / pytest-asyncio (`asyncio_mode=auto`), ruff.

**Spec:** `docs/superpowers/specs/2026-06-16-soil-water-balance-model-design.md`

---

## File Structure

- Create `backend/app/engine/soil_water_model.py` — pure math: `DayInput`, `SoilWaterModelResult`, `model_soil_water()`, `_confidence_factor()`. No I/O.
- Create `backend/app/engine/soil_water_data.py` — pure assembly (`_find_window_start`, `_assemble_daily`) + thin async `load_daily_inputs()`.
- Modify `backend/app/engine/types.py` — add `swc_source` + `swc_model` fields to `EngineRecommendation`.
- Modify `backend/app/engine/pipeline.py` — wire the model into the SWC step.
- Modify `backend/app/engine/confidence.py` — accept `swc_model_confidence` and soften the no-probe penalty for modeled sectors.
- Modify `backend/app/services/recommendation_service.py` — persist `swc_source`/`swc_model` into `inputs_snapshot`.
- Create `backend/tests/test_engine/test_soil_water_model.py`
- Create `backend/tests/test_engine/test_soil_water_data.py`
- Modify `backend/tests/test_engine/test_pipeline_soil_water.py` (new integration test file)

All test commands run from `backend/` inside the container:
`docker compose exec -T backend pytest <path> -v`
(or locally `cd backend && pytest <path> -v`).

---

## Task 1: Pure soil-water model

**Files:**
- Create: `backend/app/engine/soil_water_model.py`
- Test: `backend/tests/test_engine/test_soil_water_model.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_engine/test_soil_water_model.py
from datetime import date

from app.engine.soil_water_model import DayInput, model_soil_water

# clay-loam-ish: fc=0.30, pwp=0.15, root=0.5m → TAW = (0.30-0.15)*0.5*1000 = 75 mm
_SOIL = dict(fc=0.30, pwp=0.15, root_depth_m=0.5, kc=0.6,
             rainfall_effectiveness=0.8, application_efficiency=0.9)


def _days(start: date, n: int, *, et0, rain=0.0, irr=0.0, **kw):
    return [DayInput(day=date.fromordinal(start.toordinal() + i),
                     et0_mm=et0, rain_mm=rain, irrigation_mm=irr, **kw) for i in range(n)]


def test_big_rain_anchors_to_field_capacity():
    today = date(2026, 3, 20)
    daily = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    # 60mm*0.8 effective rain >> TAW → SWC capped at FC, depletion ~0
    assert r.swc_current == 0.30
    assert r.depletion_mm == 0.0
    assert r.seed_kind == "rain_anchored"
    assert r.last_anchor_date == date(2026, 3, 19)


def test_dry_days_after_anchor_deplete_by_et():
    today = date(2026, 3, 30)
    daily = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    daily += _days(date(2026, 3, 20), 10, et0=5.0)  # 10 dry days, ETc = 5*0.6 = 3 mm/day
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    # ~30mm depleted over 10 days from FC
    assert 28.0 <= r.depletion_mm <= 32.0
    assert r.days_since_anchor == 11
    assert r.confidence_factor >= 0.5


def test_measured_irrigation_reduces_depletion():
    today = date(2026, 3, 30)
    base = [DayInput(day=date(2026, 3, 19), et0_mm=3.0, rain_mm=60.0, irrigation_mm=0.0)]
    dry = _days(date(2026, 3, 20), 10, et0=5.0)
    irr = _days(date(2026, 3, 20), 10, et0=5.0, irr=3.0)  # 3mm*0.9 ~ offsets ETc
    r_dry = model_soil_water(daily=base + dry, today=today, **_SOIL)
    r_irr = model_soil_water(daily=base + irr, today=today, **_SOIL)
    assert r_irr.depletion_mm < r_dry.depletion_mm


def test_no_anchor_falls_back_to_static_seed():
    today = date(2026, 8, 1)
    daily = _days(date(2026, 7, 22), 10, et0=6.0)  # no rain, no irrigation
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
    daily += _days(date(2026, 3, 20), 226, et0=5.0, irr=3.0)  # ~7.5 months, all measured
    r = model_soil_water(daily=daily, today=today, **_SOIL)
    assert r.days_since_anchor and r.days_since_anchor > 200
    assert r.confidence_factor >= 0.5  # does NOT collapse


def test_deterministic():
    today = date(2026, 4, 1)
    daily = _days(date(2026, 3, 20), 12, et0=5.0, irr=2.0)
    a = model_soil_water(daily=daily, today=today, **_SOIL)
    b = model_soil_water(daily=daily, today=today, **_SOIL)
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend pytest tests/test_engine/test_soil_water_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.soil_water_model'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/engine/soil_water_model.py
"""Rain-anchored FAO-56 running soil-water balance for probe-less, flowmeter-backed sectors.

Reconstructs current rootzone SWC by integrating a daily water balance forward, crediting
measured irrigation (flowmeter) + rain in and ET0*Kc out. The deep-drainage cap in
apply_daily_balance anchors SWC to field capacity on a large recharge; confidence reflects
INPUT COMPLETENESS (weather + flowmeter continuity), not days-since-rain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.engine.water_balance import (
    DEFAULT_FC,
    DEFAULT_PWP,
    apply_daily_balance,
    compute_depletion,
    compute_taw,
)


@dataclass(frozen=True)
class DayInput:
    day: date
    et0_mm: float | None
    rain_mm: float
    irrigation_mm: float
    weather_gap: bool = False            # weather missing → ET0 carried forward
    irrigation_unmeasured: bool = False  # flowmeter offline → irrigation unknown


@dataclass(frozen=True)
class SoilWaterModelResult:
    swc_current: float
    depletion_mm: float
    taw_mm: float
    last_anchor_date: date | None
    days_since_anchor: int | None
    seed_kind: str               # "rain_anchored" | "static_fallback"
    n_gap_days: int              # days with a weather or irrigation-measurement gap
    n_days_integrated: int
    confidence_factor: float     # 0..1


_FALLBACK_ET0_MM = 4.0


def _confidence_factor(
    seed_kind: str, n_gap_days: int, n_days: int, days_since_anchor: int | None
) -> float:
    if n_days == 0:
        return 0.3
    base = 0.75 if seed_kind == "rain_anchored" else 0.5
    base -= 0.4 * (n_gap_days / n_days)            # gaps = unmeasured flux
    if days_since_anchor is not None:              # slow, bounded drift
        base -= min(0.15, days_since_anchor / 365 * 0.15)
    return max(0.3, min(0.9, round(base, 3)))


def model_soil_water(
    *,
    fc: float | None,
    pwp: float | None,
    root_depth_m: float,
    kc: float,
    rainfall_effectiveness: float,
    application_efficiency: float = 0.9,
    daily: list[DayInput],
    today: date,
) -> SoilWaterModelResult:
    fc = fc if fc is not None else DEFAULT_FC
    pwp = pwp if pwp is not None else DEFAULT_PWP
    taw = compute_taw(fc, pwp, root_depth_m)

    swc = pwp + (fc - pwp) * 0.70   # static seed at window start
    seed_kind = "static_fallback"
    last_anchor: date | None = None
    n_gap = 0
    n_days = 0
    last_et0 = _FALLBACK_ET0_MM

    for d in daily:
        n_days += 1
        day_has_gap = False

        if d.et0_mm is not None and not d.weather_gap:
            last_et0 = d.et0_mm
            et0 = d.et0_mm
        else:
            et0 = last_et0
            day_has_gap = True
        etc = et0 * kc

        rain_eff = max(0.0, d.rain_mm) * rainfall_effectiveness
        if d.irrigation_unmeasured:
            irrig_net = 0.0
            day_has_gap = True
        else:
            irrig_net = max(0.0, d.irrigation_mm) * application_efficiency

        if day_has_gap:
            n_gap += 1

        swc = apply_daily_balance(swc, etc, rain_eff, irrig_net, fc, root_depth_m)

        if swc >= fc - 1e-6:        # deep-drainage cap reached FC → recharge anchor
            last_anchor = d.day
            seed_kind = "rain_anchored"

    depletion = compute_depletion(fc, swc, root_depth_m)
    days_since_anchor = (today - last_anchor).days if last_anchor is not None else None
    confidence = _confidence_factor(seed_kind, n_gap, n_days, days_since_anchor)

    return SoilWaterModelResult(
        swc_current=round(swc, 4),
        depletion_mm=round(depletion, 2),
        taw_mm=round(taw, 2),
        last_anchor_date=last_anchor,
        days_since_anchor=days_since_anchor,
        seed_kind=seed_kind,
        n_gap_days=n_gap,
        n_days_integrated=n_days,
        confidence_factor=confidence,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend pytest tests/test_engine/test_soil_water_model.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint + commit**

```bash
docker compose exec -T backend ruff check app/engine/soil_water_model.py tests/test_engine/test_soil_water_model.py
git add backend/app/engine/soil_water_model.py backend/tests/test_engine/test_soil_water_model.py
git commit -m "feat(engine): pure rain-anchored soil-water balance model"
```

---

## Task 2: Daily-input assembly (pure) + async loader

**Files:**
- Create: `backend/app/engine/soil_water_data.py`
- Test: `backend/tests/test_engine/test_soil_water_data.py`

- [ ] **Step 1: Write the failing tests (pure assembly only)**

```python
# backend/tests/test_engine/test_soil_water_data.py
from datetime import date

from app.engine.soil_water_data import _assemble_daily, _find_window_start


def test_find_window_start_uses_last_recharge():
    # rain >= 20mm on 2026-03-19 → window starts there
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
    irrigation_mm_by_day = {}                       # no events
    reading_dates = {date(2026, 6, 1)}              # meter reported only on the 1st
    days = _assemble_daily(start, today, weather, irrigation_mm_by_day, reading_dates)
    assert days[0].irrigation_unmeasured is False   # readings present, no event → real 0
    assert days[1].irrigation_unmeasured is True    # no readings → offline


def test_assemble_marks_weather_gap_and_sums_irrigation():
    start, today = date(2026, 6, 1), date(2026, 6, 2)
    weather = {date(2026, 6, 1): (6.0, 0.0)}        # 6/2 missing
    irrigation_mm_by_day = {date(2026, 6, 1): 4.5}
    reading_dates = {date(2026, 6, 1), date(2026, 6, 2)}
    days = _assemble_daily(start, today, weather, irrigation_mm_by_day, reading_dates)
    assert days[0].irrigation_mm == 4.5
    assert days[0].weather_gap is False
    assert days[1].weather_gap is True
    assert days[1].et0_mm is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend pytest tests/test_engine/test_soil_water_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.soil_water_data'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/engine/soil_water_data.py
"""Assemble per-day soil-water model inputs from weather + flowmeter history.

Pure helpers (_find_window_start, _assemble_daily) are unit-tested; load_daily_inputs is a
thin async wrapper that queries the DB and delegates to them.
"""
from __future__ import annotations

from datetime import UTC, date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.soil_water_model import DayInput
from app.models import FlowmeterReading, IrrigationEventDetected, WeatherObservation

MAX_LOOKBACK_DAYS = 365
RECHARGE_RAIN_MM = 20.0   # daily effective-rain magnitude treated as a soil recharge


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
        # No flowmeter readings that day → meter offline → irrigation unknown.
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


async def load_daily_inputs(
    *,
    sector_id: str,
    farm_id: str,
    flowmeter_id: str,
    today: date,
    db: AsyncSession,
) -> list[DayInput]:
    floor = today - timedelta(days=MAX_LOOKBACK_DAYS)
    floor_dt = _start_of_day(floor)

    # Weather: aggregate observations to one (et0, rain) per day (max et0, summed rain).
    weather_by_day: dict[date, tuple[float | None, float]] = {}
    obs = (await db.execute(
        select(WeatherObservation)
        .where(WeatherObservation.farm_id == farm_id,
               WeatherObservation.timestamp >= floor_dt)
    )).scalars().all()
    for o in obs:
        d = o.timestamp.date()
        et0_prev, rain_prev = weather_by_day.get(d, (None, 0.0))
        et0 = o.et0_mm if et0_prev is None else (
            max(et0_prev, o.et0_mm) if o.et0_mm is not None else et0_prev)
        weather_by_day[d] = (et0, rain_prev + (o.rainfall_mm or 0.0))

    window_start = _find_window_start(weather_by_day, today, MAX_LOOKBACK_DAYS, RECHARGE_RAIN_MM)

    # Irrigation applied per day (m3/ha → mm).
    irrigation_mm_by_day: dict[date, float] = {}
    events = (await db.execute(
        select(IrrigationEventDetected)
        .where(IrrigationEventDetected.sector_id == sector_id,
               IrrigationEventDetected.date >= window_start)
    )).scalars().all()
    for e in events:
        irrigation_mm_by_day[e.date] = irrigation_mm_by_day.get(e.date, 0.0) + (e.total_m3_ha / 10.0)

    # Days the meter actually reported (to tell offline from genuinely-no-irrigation).
    reading_rows = (await db.execute(
        select(FlowmeterReading.timestamp)
        .where(FlowmeterReading.flowmeter_id == flowmeter_id,
               FlowmeterReading.timestamp >= _start_of_day(window_start))
    )).scalars().all()
    reading_dates = {ts.date() for ts in reading_rows}

    return _assemble_daily(window_start, today, weather_by_day, irrigation_mm_by_day, reading_dates)


def _start_of_day(d: date):
    from datetime import datetime
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend pytest tests/test_engine/test_soil_water_data.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint + commit**

```bash
docker compose exec -T backend ruff check app/engine/soil_water_data.py tests/test_engine/test_soil_water_data.py
git add backend/app/engine/soil_water_data.py backend/tests/test_engine/test_soil_water_data.py
git commit -m "feat(engine): assemble soil-water model inputs from weather + flowmeter history"
```

---

## Task 3: Surface `swc_source` + model metadata on the recommendation

**Files:**
- Modify: `backend/app/engine/types.py` (EngineRecommendation, after `kc` field ~line 199)
- Modify: `backend/app/services/recommendation_service.py:22-41` (`_make_inputs_snapshot`)

- [ ] **Step 1: Add fields to `EngineRecommendation`**

In `backend/app/engine/types.py`, in the `EngineRecommendation` dataclass, add after `kc: float | None = None`:

```python
    swc_source: str | None = None          # "probe_weighted" | "water_balance_model" | "default_estimate"
    swc_model: dict | None = None          # model metadata when swc_source == "water_balance_model"
```

- [ ] **Step 2: Persist them in the snapshot**

In `backend/app/services/recommendation_service.py`, inside `_make_inputs_snapshot`, add to the `snap` dict (before the `return`):

```python
        "swc_source": eng.swc_source,
        "swc_model": eng.swc_model,
```

- [ ] **Step 3: Verify the suite still imports/builds**

Run: `docker compose exec -T backend pytest tests/test_engine -q`
Expected: PASS (no behavior change yet; existing tests unaffected)

- [ ] **Step 4: Commit**

```bash
git add backend/app/engine/types.py backend/app/services/recommendation_service.py
git commit -m "feat(engine): add swc_source + swc_model to recommendation snapshot"
```

---

## Task 4: Wire the model into the pipeline

**Files:**
- Modify: `backend/app/engine/pipeline.py` (the SWC step ~lines 429-438, and the `EngineRecommendation(...)` construction ~line 521)

- [ ] **Step 1: Replace the SWC determination block**

In `backend/app/engine/pipeline.py`, find:

```python
        # Step 6: Probe interpretation → rootzone SWC
        probes: ProbeSnapshot = await probe_interpreter.interpret_probes(ctx, db)
```
…and the line:
```python
        wb = water_balance.build_water_balance(ctx, probes.rootzone.swc_current)
```

Replace that `wb = ...` line with:

```python
        swc_source = probes.rootzone.swc_source
        swc_model_result = None
        swc_for_wb = probes.rootzone.swc_current
        if swc_for_wb is None and farm_id:
            from app.engine.soil_water_data import load_daily_inputs
            from app.engine.soil_water_model import model_soil_water
            from app.models import Flowmeter

            flowmeter = (await db.execute(
                select(Flowmeter).where(
                    Flowmeter.sector_id == sector_id,
                    Flowmeter.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if flowmeter is not None:
                daily = await load_daily_inputs(
                    sector_id=sector_id,
                    farm_id=farm_id,
                    flowmeter_id=flowmeter.id,
                    today=target_date,
                    db=db,
                )
                swc_model_result = model_soil_water(
                    fc=ctx.field_capacity,
                    pwp=ctx.wilting_point,
                    root_depth_m=ctx.root_depth_m,
                    kc=ctx.kc,
                    rainfall_effectiveness=ctx.rainfall_effectiveness,
                    application_efficiency=ctx.irrigation_efficiency,
                    daily=daily,
                    today=target_date,
                )
                swc_for_wb = swc_model_result.swc_current
                swc_source = "water_balance_model"
                log.append(
                    f"SoilWaterModel: SWC={swc_for_wb}, source={swc_model_result.seed_kind}, "
                    f"days_since_anchor={swc_model_result.days_since_anchor}, "
                    f"conf={swc_model_result.confidence_factor}"
                )

        wb = water_balance.build_water_balance(ctx, swc_for_wb)
```

- [ ] **Step 2: Pass model metadata into the recommendation**

In the `EngineRecommendation(...)` construction, add these keyword args (next to `swc_current=wb.swc_current,`):

```python
            swc_source=swc_source,
            swc_model=(
                {
                    "seed_kind": swc_model_result.seed_kind,
                    "last_anchor_date": (
                        swc_model_result.last_anchor_date.isoformat()
                        if swc_model_result.last_anchor_date else None
                    ),
                    "days_since_anchor": swc_model_result.days_since_anchor,
                    "n_gap_days": swc_model_result.n_gap_days,
                    "confidence_factor": swc_model_result.confidence_factor,
                }
                if swc_model_result is not None else None
            ),
```

- [ ] **Step 3: Run the engine suite**

Run: `docker compose exec -T backend pytest tests/test_engine -q`
Expected: PASS (probe sectors unchanged; no flowmeter in unit fixtures → static fallback unchanged)

- [ ] **Step 4: Commit**

```bash
git add backend/app/engine/pipeline.py
git commit -m "feat(engine): use soil-water model for probe-less flowmeter sectors"
```

---

## Task 5: Confidence reflects modeled SWC (input-driven)

**Files:**
- Modify: `backend/app/engine/confidence.py` (`score` signature ~line 31; no-probe penalty ~lines 49-51)
- Modify: `backend/app/engine/pipeline.py` (the `confidence.score(...)` call ~line 470)
- Test: `backend/tests/test_engine/test_confidence.py` (add one test)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_engine/test_confidence.py`. **Build `ctx`, `probes` (with
`rootzone.has_data == False`), and `weather` by copying the exact construction an existing
no-probe test in this file already uses** (e.g. the setup inside
`test_no_irrigation_system_penalises`) — do not invent a new helper; mirror the file's
established pattern. Then:

```python
def test_modeled_swc_softens_no_probe_penalty():
    from app.engine import confidence
    # ctx, probes (rootzone.has_data=False), weather — built exactly like the
    # other no-probe tests in this file.
    base = confidence.score(ctx, probes, weather, None)
    modeled = confidence.score(ctx, probes, weather, None, swc_model_confidence=0.75)
    # Softened penalty: 0.25*(1-0.75)=0.0625 instead of 0.25 → higher score.
    assert modeled.score > base.score
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend pytest tests/test_engine/test_confidence.py::test_modeled_swc_softens_no_probe_penalty -v`
Expected: FAIL — `TypeError: score() got an unexpected keyword argument 'swc_model_confidence'`

- [ ] **Step 3: Implement the softened penalty**

In `backend/app/engine/confidence.py`, change the `score` signature:

```python
def score(
    ctx: SectorContext,
    probes: ProbeSnapshot,
    weather: WeatherContext,
    anomalies: list[str] | list[AnomalyObj] | None = None,
    swc_model_confidence: float | None = None,
) -> ConfidenceResult:
```

Replace the no-probe penalty block:

```python
    if not rz.has_data:
        _pen(conf, penalties, warnings, "No probe data", 0.25)
        conf -= 0.25
```

with:

```python
    if not rz.has_data:
        if swc_model_confidence is not None:
            pen = round(0.25 * (1.0 - swc_model_confidence), 3)
            _pen(conf, penalties, warnings,
                 f"SWC from water-balance model (conf {swc_model_confidence:.2f})", pen)
            conf -= pen
        else:
            _pen(conf, penalties, warnings, "No probe data", 0.25)
            conf -= 0.25
```

- [ ] **Step 4: Pass the model confidence from the pipeline**

In `backend/app/engine/pipeline.py`, change the confidence call:

```python
        conf: ConfidenceResult = confidence.score(ctx, probes, weather, probes.anomalies_detected)
```
to:
```python
        conf: ConfidenceResult = confidence.score(
            ctx, probes, weather, probes.anomalies_detected,
            swc_model_confidence=(swc_model_result.confidence_factor if swc_model_result else None),
        )
```

- [ ] **Step 5: Run tests to verify pass**

Run: `docker compose exec -T backend pytest tests/test_engine/test_confidence.py -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
docker compose exec -T backend ruff check app/engine/confidence.py app/engine/pipeline.py
git add backend/app/engine/confidence.py backend/app/engine/pipeline.py backend/tests/test_engine/test_confidence.py
git commit -m "feat(engine): confidence reflects modeled-SWC quality instead of flat no-probe penalty"
```

---

## Task 6: End-to-end pipeline integration test

**Files:**
- Create: `backend/tests/test_engine/test_pipeline_soil_water.py`

This test seeds a probe-less sector that HAS an active flowmeter, with weather + flowmeter
history, runs the pipeline, and asserts the recommendation used the model (not the static seed).

- [ ] **Step 1: Write the failing test**

The repo's engine tests run against a **pre-seeded** test DB (see `test_pipeline.py`'s
`seed_farm_id` / `seed_sectors` fixtures, which query the already-seeded "Herdade do
Esporão" farm). Follow that pattern: build on a seeded sector rather than constructing a
farm from scratch. Note `pipeline.run` is called `run(sector_id, target_date, db, farm_id=...)`.

```python
# backend/tests/test_engine/test_pipeline_soil_water.py
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.engine.pipeline import RecommendationPipeline
from app.models import (
    Farm, Flowmeter, FlowmeterReading, IrrigationEventDetected, Plot, Probe, Sector,
    WeatherObservation,
)


@pytest.mark.asyncio
async def test_probeless_flowmeter_sector_uses_water_balance_model(db):
    """A probe-less sector with a flowmeter must get swc_source='water_balance_model'
    and a depletion that reflects measured irrigation/ET — not the static 30%."""
    today = date(2026, 6, 16)

    # Use the pre-seeded farm/sector (same data test_pipeline.py relies on), queried inline.
    seed_farm_id = (await db.execute(
        select(Farm.id).where(Farm.name == "Herdade do Esporão")
    )).scalar_one()
    sector = (await db.execute(
        select(Sector).join(Plot, Sector.plot_id == Plot.id).where(Plot.farm_id == seed_farm_id)
    )).scalars().first()

    # Guarantee probe-less: delete any probes on the chosen sector.
    for p in (await db.execute(select(Probe).where(Probe.sector_id == sector.id))).scalars().all():
        await db.delete(p)

    # Attach an active flowmeter.
    fm = Flowmeter(sector_id=sector.id, external_device_id=999001, is_active=True)
    db.add(fm)
    await db.flush()

    # ~30 days of daily weather (et0=5), one early big-rain anchor day, plus per-day
    # flowmeter readings (so no day is flagged offline) and a few irrigation events.
    for i in range(30):
        d = today - timedelta(days=29 - i)
        ts = datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
        db.add(WeatherObservation(
            farm_id=seed_farm_id, timestamp=ts,
            rainfall_mm=40.0 if i == 0 else 0.0, et0_mm=5.0,
        ))
        db.add(FlowmeterReading(flowmeter_id=fm.id, timestamp=ts, value_m3_ha=0.0))
    for i in (10, 17, 24):
        d = today - timedelta(days=29 - i)
        db.add(IrrigationEventDetected(
            flowmeter_id=fm.id, sector_id=sector.id,
            start_time=datetime(d.year, d.month, d.day, 6, tzinfo=UTC),
            end_time=datetime(d.year, d.month, d.day, 8, tzinfo=UTC),
            total_m3_ha=30.0, peak_m3_ha=15.0, num_readings=8, date=d,
        ))
    await db.flush()

    rec = await RecommendationPipeline().run(sector.id, today, db, farm_id=seed_farm_id)

    assert rec.swc_source == "water_balance_model"
    assert rec.swc_model is not None
    # Static seed would pin depletion at exactly 30% of TAW; the model must differ.
    assert abs((rec.depletion_mm / rec.taw_mm) - 0.30) > 0.02
```

> Verify the `Flowmeter` / `FlowmeterReading` / `IrrigationEventDetected` constructor kwargs
> against the model definitions (`app/models/`) before running — match their exact required
> columns; adjust only field names if the models differ from the above.

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend pytest tests/test_engine/test_pipeline_soil_water.py -v`
Expected: FAIL — if Tasks 1-5 are in place the assertions should pass; before them, `swc_source` is `None`/`"no probes registered"`, not `"water_balance_model"`.

- [ ] **Step 3: Make it pass**

Tasks 1-5 already implement the behavior. Resolve only ORM-constructor/seeding details (match the model column names in `app/models/`) until the assertions pass. No production code change should be needed; if one is, it indicates a gap in Task 4 wiring — fix there.

- [ ] **Step 4: Run the full engine suite**

Run: `docker compose exec -T backend pytest tests/test_engine -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_engine/test_pipeline_soil_water.py
git commit -m "test(engine): e2e — probe-less flowmeter sector uses soil-water model"
```

---

## Final verification

- [ ] Run full backend suite: `docker compose exec -T backend pytest -q`
- [ ] Lint: `docker compose exec -T backend ruff check app/engine app/services`
- [ ] Manual sanity on prod data later (out of scope for this plan): a known probe-less + flowmeter sector should now show a depletion that moves day to day and a `swc_source` of `water_balance_model` in its `inputs_snapshot`.

## Notes / deferred (per spec — do NOT build here)

- Frontend display of `swc_source` / `days_since_anchor` (separate follow-on).
- Auto-calibration / `evaluate_model_against_probe()` hook.
- Coverage for probe-less + flowmeter-less sectors (stay on static seed).

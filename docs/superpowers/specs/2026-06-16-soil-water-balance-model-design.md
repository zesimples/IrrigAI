# Soil-Water Balance Model for Probe-less Sectors — Design

**Date:** 2026-06-16
**Status:** Approved (design) — pending implementation plan

## Problem

For sectors **without a soil probe**, the engine's water balance does not model soil
moisture at all. `engine/water_balance.py::build_water_balance` seeds soil-water
content (SWC) at a fixed **70% of available water** when `swc_probe is None`, pinning
depletion at a constant ~30% of TAW regardless of weather, rain, or irrigation:

```python
else:
    swc = pwp + (fc - pwp) * 0.70   # no probe → static seed
```

The FAO-56 running balance the module's docstring advertises (`apply_daily_balance`)
is **dead code — never called anywhere**. So a probe-less sector's recommendation is
driven only by today's ET₀×Kc and the rain-skip logic, on top of a constant soil
assumption. This is what the pervasive "fiabilidade média 40% — alguns parâmetros
foram estimados" reflects.

This also blocks a credible water-efficiency/savings dashboard: on flowmeter-only
sectors, "actual vs recommended" would compare measured water against a static guess.

## Goal

Replace the static seed — **only for probe-less sectors that have a flowmeter** — with
a deterministic, rain-anchored FAO-56 running balance reconstructed each run from
weather history + flowmeter-measured irrigation. Produce a trustworthy modeled SWC and
an honest, decaying confidence.

## Scope decisions (locked)

1. **Probe-less sectors only.** Sectors with a probe keep using probe SWC unchanged
   (the probe is ground truth; the model would only be a worse estimate there).
2. **Flowmeter-backed only.** Enable the model only for probe-less sectors that have an
   active flowmeter, so the dominant balance input (irrigation applied) is *measured*,
   never guessed. Probe-less + flowmeter-less sectors keep today's static seed.
3. **Rain-anchored seeding + measured-flux integration.** The end-of-rainy-season
   recharge (e.g., Conqueiros' last good rain was **19/03/2026**) sets SWC to field
   capacity — a single strong annual anchor. Through the long Alentejo dry season
   (~Apr–Nov, no rain) the balance runs off that anchor using **measured** fluxes:
   flowmeter irrigation in, ET₀ out. Accuracy therefore does **not** depend on more
   rain — it depends on input completeness. (See "Confidence" — this corrects an
   earlier draft that wrongly decayed confidence with days-since-rain, which would
   collapse precisely during the irrigation season.)
4. **Approach A — replay-from-source (stateless).** Each recommendation run recomputes
   the balance from raw `WeatherObservation` + `IrrigationEventDetected` history. No new
   state table, no migration, deterministic, idempotent, robust to missed worker runs
   (chosen deliberately after the June 2026 outage showed how fragile a "daily job must
   always run" assumption is).

## Why most effective on flowmeter sectors

- **Probe sectors:** the probe directly measures SWC → the model is redundant (at most a
  background cross-check). Probe stays authoritative.
- **Flowmeter (probe-less) sectors:** no soil measurement, but the flowmeter measures the
  single most variable balance input (irrigation applied). The model reconstructs SWC
  from a measured dominant term — a large upgrade over the static 30%.
- **Both-sensor sectors:** ideal to validate/calibrate the model against the probe and
  transfer tuned parameters to flowmeter-only sectors of the same soil/crop.

## Components (each independently testable)

### 1. `engine/soil_water_model.py` — pure, synchronous (the math)

Input dataclass `SoilWaterInputs`:
- soil/crop params: `fc, pwp, root_depth_m, kc, rainfall_effectiveness,
  application_efficiency` (**default 0.9** — drip)
- `daily`: ordered `list[DayInput(date, et0_mm, rain_mm, irrigation_mm, is_gap)]` from the
  lookback-window start → today
- `today`

Logic (no separate "anchor search" — anchors emerge from the integration):
- Seed SWC at the window start with the static 70%-of-TAW assumption
  (`seed_kind="static_fallback"`).
- Integrate forward day-by-day reusing existing `apply_daily_balance`:
  `ETc = et0 × kc`, `rain_eff = rain × rainfall_effectiveness`,
  `irrig_net = irrigation_mm × application_efficiency`. The function already caps at
  field capacity (deep drainage) and floors at ~0.
- An **anchor** is any day the running SWC reaches field capacity via that FC-cap (a
  large effective rain — or rain+irrigation — fills the soil and erases prior seed
  error). `last_anchor_date` = the most recent such day; `days_since_anchor` = days
  since it (or days since window start if no FC-hit occurred). `seed_kind` becomes
  `"rain_anchored"` once at least one FC-hit has occurred in the window, else stays
  `"static_fallback"`.
- Count `n_gap_days` (days with carried-forward ET₀).

This makes the seed's influence self-correcting: the further back the last FC-hit, the
more the early static seed has been washed out by a real recharge event.

Output `SoilWaterModelResult`:
`swc_current, depletion_mm, last_anchor_date, days_since_anchor, seed_kind,
n_gap_days, n_days_integrated, confidence_factor`.

`confidence_factor` is driven by **input completeness, not days-since-rain** (see
"Confidence"). Reuses `apply_daily_balance`, `compute_taw`, `compute_depletion`.

### 2. `engine/soil_water_data.py` — async loader (the I/O boundary)

Given `sector`, `farm_id`:
- **Dynamic lookback to the last recharge.** Walk `WeatherObservation` backward to find
  the most recent significant rain (effective rain ≥ a recharge threshold, ~enough to
  refill the root zone) and start the window there; cap at **365 days** if none found.
  This guarantees the single annual spring anchor (e.g., 19/03) stays in-window all dry
  season — a fixed 120-day window would lose it by late summer and wrongly fall back to
  the static seed mid-irrigation-season.
- pull `WeatherObservation` daily `et0_mm`/`rainfall_mm` for the farm over the window
- aggregate `IrrigationEventDetected` per day for the sector (`Σ total_m3_ha ÷ 10 → mm`)
- **distinguish "meter offline" from "genuinely didn't irrigate"** per day using
  `FlowmeterReading` presence for the sector's flowmeter:
  - readings present that day + no detected event → **genuine `irrigation_mm = 0`**
  - **no readings that day → meter offline → `irrigation_unmeasured=True`** (do NOT
    assume 0); these days are confidence holes, counted like weather gaps
- emit the ordered `DayInput(date, et0_mm, rain_mm, irrigation_mm, is_gap,
  irrigation_unmeasured)` list; for weather gaps carry forward last known ET₀

Kept separate from the math so the model unit-tests with no DB.

### 3. `pipeline.py` wiring (SWC determination step)

- `probes.rootzone.swc_current is not None` → unchanged (probe authoritative).
- else sector has an active flowmeter → loader + model → pass modeled SWC into
  `build_water_balance`; set `swc_source = "water_balance_model"`; thread
  `days_since_anchor`, `last_anchor_date`, `confidence_factor`.
- else → unchanged static 70% (`swc_source = "default_estimate"`).

### 4. `confidence.py` — input-completeness driven (not days-since-rain)

Add a `water_balance_model` source. Because the dominant fluxes are measured (flowmeter
irrigation + weather ET₀) off a strong annual anchor, confidence must **hold steady at a
medium level through a rainless dry season** and drop only when inputs degrade:

- **Primary drivers (sharp):** continuity of flowmeter irrigation data and of
  `WeatherObservation` — `n_gap_days` and any flowmeter ingestion gap cut confidence
  hard (a gap = unmeasured flux = real accuracy hole; this is exactly what the recent
  outage was).
- **Secondary driver (slow, bounded):** a small drift term for accumulated unmeasured
  error since the last FC anchor — capped, with a floor, so months-on-one-anchor lands
  at "moderate," never collapsing and never "high."

This deliberately replaces the rejected days-since-anchor decay.

### 5. Snapshot surfacing

Add `swc_source, last_anchor_date, days_since_anchor, model_confidence` to
`inputs_snapshot`. Frontend display is a later follow-on; the backend just exposes them.

### 6. Calibration hook (designed-in, not auto-run)

Pure `evaluate_model_against_probe()` for both-sensor sectors: run the model, compare to
probe SWC, return an error metric to tune `application_efficiency` /
`rainfall_effectiveness`. Available as a script/test; no auto-tuning now.

## Data flow

`WeatherObservation` + `IrrigationEventDetected` → `soil_water_data` loader →
ordered daily list → `soil_water_model` (anchor + integrate) → modeled SWC + confidence
→ `pipeline` → `build_water_balance` → recommendation (depletion, trigger, dosage, stress
projection all now model-based) → `inputs_snapshot` exposes source/anchor/confidence.

## Edge cases / error handling

- **No recharge found within 365 days**: static-70% seed at the 365-day cap, mark
  `seed_kind="static_fallback"`, lower confidence — still better than the flat static
  seed because it credits measured irrigation + ET since then.
- **Weather gaps** (e.g., during the MyIrrigation outage): carry forward last ET₀, flag
  `n_gap_days`, cut confidence — never silently uses zero ET.
- **Flowmeter ingestion gap**: irrigation is unmeasured for those days → treat as a
  confidence hole (do not assume 0 applied if the meter was simply offline); flag it.
- **Units/efficiency**: `m³/ha ÷ 10 → mm`; `application_efficiency` default **0.9**
  (drip). FC-cap and zero-floor already handled in `apply_daily_balance`.
- **Flowmeter present, genuinely no irrigation**: `irrigation_mm = 0` those days — fine.
- **Compute bound**: up to ~365 daily steps per run (one cheap loop); acceptable.

## Testing (TDD)

Pure model (no DB): anchor reset on big rain; irrigation crediting; no-anchor fallback;
weather-gap handling; monotonic confidence decay; determinism/idempotency.
Loader: multi-event/day aggregation + m³/ha→mm conversion; farm-weather join; gap marking.
Pipeline integration: probe-less + flowmeter → `swc_source="water_balance_model"` with
non-static depletion; probe sector unchanged; probe-less + no-flowmeter unchanged static.

## Out of scope (YAGNI)

- Auto-calibration / parameter tuning (only the measurement hook ships).
- Frontend UI changes (backend exposes fields; display is a follow-on).
- Persisted daily-state table (approach B) and hybrid reconciliation (approach C).
- Coverage for probe-less + flowmeter-less sectors (stay on static seed).

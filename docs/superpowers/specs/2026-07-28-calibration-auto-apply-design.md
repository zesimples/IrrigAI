# Probe-calibration auto-apply — design

**Date:** 2026-07-28
**Status:** implemented; gate inputs amended by the final review (see *Amendment*)
**Scope:** backend only (engine, service, scheduler, one migration, one API field)

## Amendment (2026-07-28, final whole-branch review) — gates key on the RESOLVED source

Gates 1 and 4 below were originally specified against raw DB flags
(`SectorCropProfile.is_customized`, "a `probe_calibration` row exists"). **That wording is
superseded: both gates now key on `before.source`, the source `resolve_soil_bounds` actually
chose** — `scp_override` for gate 1, `probe_calibrated` for gate 4. The tables and prose in
this document have been updated in place; this note records why.

The raw flags deadlocked two real populations, in both cases *against* this design's stated
intent:

- **A stale calibration blocked its own replacement forever.** `soil_bounds` ignores a
  calibration older than `CALIB_MAX_AGE_DAYS` (90) and falls through to the preset. So for a
  sector calibrated in April whose probe went offline 100 days and is now back with 30 clean
  days, `before.fc` is the preset 0.16 while the candidate is 0.44 — a 0.28 move measured
  against a preset the sector was never measured on, i.e. `delta_exceeds_cap`, and the row
  can only get staler. Gate 4 exists to guard *movement away from a previously trusted
  probe-derived value*; a calibration the engine has stopped trusting is not that value.
- **`is_customized` often does not govern soil bounds.** `PUT /crop-profile` sets it on ANY
  profile edit, but `soil_bounds` honours `scp_override` only when BOTH `scp_fc` and
  `scp_pwp` are non-null. An agronomist bumping `mad` on a clamped sector whose soil fields
  are NULL made the gate report `manual_override` every Monday while the sector stayed pinned
  at ~0% depletion — the exact bug this feature exists to fix. Gate 1 exists because *a
  deliberate human soil edit* outranks measurement; a `mad` edit is not a soil edit.

Keying on the resolved source is therefore strictly more faithful to the intent: it gates on
the value the engine computes depletion from. The policy parameters were renamed
`bounds_from_manual_override` / `bounds_from_prior_calibration` so the names stop lying, and
`soil_bounds` now exports named `SOURCE_*` constants for the coupling.

**The invariant is unchanged and still absolute:** the auto path never writes
`SectorCropProfile.is_customized`. A human's non-soil customization simply no longer blocks a
sector whose bounds it does not govern.

## Problem

Since the 2026-07-15 calibration-history cycle, the weekly scheduler job creates
`ProbeCalibrationRun` rows with status `candidate` and never changes live soil bounds.
Only a human pressing *Calibração AI* (`POST /sectors/{id}/auto-calibration/run`) or
`POST /calibration-runs/{run_id}/apply` promotes a run.

The consequence is a **coverage** failure, not a freshness one. Sectors whose plot preset
FC sits below the probe's real VWC envelope have their soil-water state clamped: depletion
computes to ~0, the engine recommends "never irrigate", and it stays wrong until someone
clicks per sector. At Innoliva that is 77 sectors; roughly 18 of 76 sectors were previously
measured as permanently pinned. Nobody clicks a button 77 times, so the deterministic
calibration that would fix these sectors is computed weekly and then discarded.

This design lets the weekly job apply its own results, gated by a policy that protects
human edits and rejects untrustworthy windows.

### Non-goal: the LLM does not participate

This was the originating question ("can the *Explicação com IA · sonda* feedback calibrate
CC/PMP?"). It cannot and must not. `compute_probe_signal_stats` strips every raw scalar
before the LLM sees it (`probe_signal.py`, `_latest_vwc_raw` popped), and since the P2
evidence cycle raw VWC/FC/PWP values are not citable. The model has no numeric channel to
emit a soil bound from, by construction. Soil numbers stay deterministic; the AI layer
explains them. The quality signals reused here (flatline, staleness) are the *deterministic*
statistics that feed the AI card, not the model's output.

## Approach

A pure policy function decides; the service and scheduler only wire it up. This mirrors
`engine/soil_bounds.resolve_soil_bounds` — a pure, unit-tested resolver with all DB access
outside it. Thresholds become table-driven unit tests with no fixtures, which matters
because these values will be tuned after a season of real data.

Rejected alternatives:

- **Policy inline in the service** — thresholds only reachable through async DB tests, and
  decision logic interleaved with persistence.
- **A second scheduler job promoting candidates** — preserves a candidate queue we
  deliberately stop maintaining, adds a second Redis lock and an ordering constraint before
  the 05:00 recommendation run, and judges candidates against bounds that may have moved
  since compute.

## Components

### New: `backend/app/engine/calibration_policy.py` (pure)

```python
AUTO_APPLY_MAX_DELTA_M3M3 = 0.05
AUTO_APPLY_FLATLINE_STD_M3M3 = 0.003   # same floor as probe_signal._FLATLINE_STD

@dataclass(frozen=True)
class CalibrationQuality:
    probe_hours_since_reading: float | None
    all_depths_flatlined: bool
    # No `method` field: ProbeCalibrationResult.method already carries it, and
    # duplicating it would give the metric label two sources of truth.

@dataclass(frozen=True)
class AutoApplyDecision:
    apply: bool
    reason: str                        # applied | manual_override | probe_stale
                                       # | flatline | delta_exceeds_cap

def evaluate_auto_apply(
    candidate: ProbeCalibrationResult,
    before: ResolvedSoilBounds,
    quality: CalibrationQuality,
    *,
    bounds_from_manual_override: bool,    # before.source == "scp_override"
    bounds_from_prior_calibration: bool,  # before.source == "probe_calibrated"
) -> AutoApplyDecision
```

Both flags describe the *resolved* source of `before`, not raw DB rows — see **Amendment**.
The service derives them from `before.source`; the policy stays pure and takes booleans, so
the thresholds remain testable without fixtures.

### Changed: `ProbeCalibrationService`

- New `compute_and_auto_apply(sector_id, db)`: resolves before-bounds, builds
  `CalibrationQuality`, derives the two gate flags from `before.source`, calls the policy,
  then either promotes through the existing `apply_run()` or returns having persisted nothing.
  It returns an `AutoApplyOutcome` (the decision plus before/candidate FC+refill, the resolved
  source and the method) so the sweep can log those values *after* the sector's savepoint has
  released — a rolled-back sector must never leave a line claiming it was applied.
- `compute_all_for_farm(farm_id, db, *, auto_apply: bool)` routes per sector and returns
  counts instead of a bare int.

`CalibrationQuality` costs no extra queries. `all_depths_flatlined` is the per-depth standard
deviation of the same 30-day VWC series the calibrator has already loaded (a depth counts as
usable when it cleared the plausibility filter); `probe_hours_since_reading` comes from
`Probe.last_reading_at`, compared against `engine/staleness.PROBE_VERY_STALE_H`.

### Changed: `Farm`, `FarmUpdate`, `FarmOut`

`calibration_auto_apply: bool`, `nullable=False`, `server_default="false"`. Toggled through
the existing `PUT /farms/{farm_id}` (ownership already enforced by `Access`).

### Changed: `scheduler._run_recompute_probe_calibration`

Reads the per-farm flag and passes it down. Job schedule unchanged.

### Unchanged and load-bearing

`apply_run()`, the resolver precedence in `engine/soil_bounds`, and both manual endpoints.
The auto path calls `apply_run()` but — unlike the manual endpoints — **never clears
`is_customized`**.

## The policy

Evaluation order, first match wins:

| # | Condition | Reason |
|---|---|---|
| 0 | `compute_sector_calibration` returned `None` | *no candidate; counted, nothing persisted* |
| 1 | `before.source == "scp_override"` (a human soil edit governs the bounds) | `manual_override` |
| 2 | `probe.last_reading_at` older than `PROBE_VERY_STALE_H` (72h), or `None` | `probe_stale` |
| 3 | Every usable depth flatlined (std < 0.003) | `flatline` |
| 4 | `before.source == "probe_calibrated"` **and** (\|Δfc\| > 0.05 or \|Δrefill\| > 0.05) | `delta_exceeds_cap` |
| — | otherwise | `applied` |

Gates 1 and 4 read the resolved source, not `is_customized` / "a `probe_calibration` row
exists" as first drafted — see **Amendment** for the two deadlocks that wording caused.

Gate 0 is free: the plausibility guard (`is_plausible_calibration`: FC ∈ [0.10, 0.60],
spread ≥ 0.03) and the 48-reading floor already live inside `compute_sector_calibration`,
which returns `None` rather than an implausible result.

Gate 2 treats a missing `last_reading_at` as stale, following the same convention as
`is_calibration_stale`.

Gate 3 requires **all** depths flat, not any. A single flat deep sensor below the root zone
is normal behaviour — no root uptake, no drainage — not a stuck sensor.

### Gate 4: the delta cap

Compares the effective bounds the engine uses today (`resolve_sector_soil_bounds`) against
the candidate's `observed_fc` / `observed_refill`. The boundary is exclusive: exactly 0.05
applies, `> 0.05` blocks.

It exists because the calibration reads a 30-day percentile envelope and inherits whatever
that window contained. Two real failure modes:

- **Window too wet** (line flush, repair test, unusually rainy month): P95 shifts up, FC
  inflates, TAW inflates, depletion under-reads, the engine under-irrigates a drying sector.
- **Window too dry** (harvest shutdown, valve left closed): the envelope collapses, FC
  under-reads, depletion over-reads, the engine over-irrigates.

Neither is caught by `is_plausible_calibration`, because both produce plausible absolute
values. They are only detectable as *movement* against a previously trusted value.

Both FC and refill are checked because TAW is the spread `(FC − PWP) × root_depth`. A
candidate could hold FC steady, drop refill by 0.08, and inflate TAW by a third while every
absolute value stays plausible.

**The cap applies only while the live bounds ARE probe-derived** (`before.source ==
"probe_calibrated"`). When `before` is a soil-texture table lookup — never calibrated, or
calibrated so long ago that the resolver ignores it — it was never measured on that sector.
Treating distance from an unmeasured guess as evidence of anomaly inverts the logic — the
larger that distance, the more likely the preset is the thing that is wrong, which *is* the
clamp bug. So a first (or post-staleness) application is uncapped, and the cap guards every
run made against a value the engine currently trusts.

For calibration: 0.05 m³/m³ over a 0.8 m olive root zone is ~40 mm of TAW, comparable to a
whole dose. The cap is a catastrophe bound, not a fine filter.

### Two deliberate deviations from first-draft guardrails

- **`method="cycles"` is not required.** `envelope` is the fallback the calibrator uses when
  a sector has fewer than 3 clean irrigation cycles — which describes most clamp-affected
  sectors. Gating on `cycles` would reject exactly the population this feature targets.
  `method` is recorded and labelled in the metric, never gated.
- **No minimum-change threshold.** A passing sector gets a fresh `applied` row every Monday
  even for a 0.001 move. Storage is trivial (~52 rows/sector/year, ~4k/year for Innoliva);
  the cost is interpretive — "when did bounds actually change" becomes a value-diff rather
  than a row count, and the audit log carries a weekly entry per sector. Add the threshold
  later if it buries the signal.

## Data flow

```
Mon 04:00 UTC  _run_recompute_probe_calibration
  └─ _run_per_farm_job (Redis lock, partial-failure classification — unchanged)
       └─ per active farm: read farm.calibration_auto_apply
            └─ compute_all_for_farm(farm_id, db, auto_apply=flag)
                 └─ per active sector (active_records), each in db.begin_nested():
                      flag off  → compute_and_record(apply=False)   # unchanged behaviour
                      flag on   → compute_and_auto_apply()
                                    ├─ resolve before-bounds
                                    ├─ build CalibrationQuality
                                    ├─ evaluate_auto_apply(...)
                                    ├─ apply  → apply_run() + audit(user_id=None)
                                    └─ skip   → persist nothing, log + metric
       └─ commit per farm
Mon 05:00 UTC  daily_recommendations picks up the new bounds
```

No explicit recommendation regeneration: the calibration job runs at 04:00 and daily
recommendations at 05:00, so applied bounds reach recommendations an hour later. The 2-hourly
alert check also runs through `RecommendationPipeline.run()` and picks them up.

Persistence outcomes, exhaustively:

| Condition | `probe_calibration_run` | `probe_calibration` projection | `is_customized` |
|---|---|---|---|
| Flag off | `candidate` row | untouched | untouched |
| Flag on, gates pass | `applied` row, prior → `superseded` | upserted | **untouched** |
| Flag on, gate blocks | nothing | untouched | untouched |
| No candidate computable | nothing | untouched | untouched |

Opt-out farms keep today's candidate queue exactly as it works now, which is what makes the
per-farm rollout meaningful.

Applied runs are audited as `probe_calibration_auto_applied` with `user_id=None` (the column
is nullable; `audit.log` never raises). That distinguishes scheduler-applied from
human-applied bounds after the fact.

## Rollout

Per-farm opt-in via the `Farm` flag, default off. Enable one farm (e.g. Esporão), inspect a
weekly run's logs and metrics, then widen to Innoliva's 77 sectors.

**No frontend control is in scope.** There is no farm-settings surface today and adding one
to flip an ops flag is not warranted — toggle via `PUT /farms/{id}` or SQL.

Deploy order follows the documented project rule: `Farm` is queried by the dashboard,
ingestion, and every scheduler job, so an image serving before its migration breaks far more
than calibration. Run `alembic upgrade head` **before** swapping `backend` / `worker`.

## Observability

Blocked runs leave no row, so this is the only trace:

```python
calibration_auto_apply_total = Counter(
    "calibration_auto_apply_total",
    "Weekly probe-calibration auto-apply decisions",
    ["result", "reason", "method"],
)
```

`result` ∈ {`applied`, `skipped`, `no_candidate`, `error`}; ~20 series, no farm or sector
labels. `no_candidate` is counted deliberately: coverage is the goal of this feature, so
"how many sectors *cannot* be calibrated" is the number that says whether it worked, and it
is invisible today. Tension/Watermark sectors sit permanently in that bucket, which is
honest rather than noisy.

Logging: one INFO per applied sector with before/after FC and refill; one WARNING per
quality-blocked sector with both value pairs; one per-farm summary
(`farm=X applied=N skipped=M no_candidate=K failed=F`) so the worker log answers "did Monday
do anything" at a glance.

**Counters, metrics and per-sector logs are emitted only after the sector's savepoint has
released.** A failure in `RELEASE SAVEPOINT` surfaces at `__aexit__`, so incrementing inside
the block let one sector count as both `applied` and `error` (`counts.applied` never
decrements) and made the summary claim `applied=N` for bounds that were rolled back. Data
integrity was never at risk — this is about the observability not lying.

No new alert producer. Per the alert-ownership rule a new producer needs its own `source` and
`rule_key`s, and blocked runs are informational rather than actionable — the metric plus the
manual button covers it.

## Error handling

**Per-sector isolation becomes a savepoint.** `compute_all_for_farm` already wraps each
sector in `try/except Exception: logger.exception(...)`, but the body does `db.add()` +
`await db.flush()`. When a flush fails the async session needs a rollback before reuse, so
swallowing the exception and continuing raises `PendingRollbackError` on the next sector —
one bad sector takes down the remaining 76. Auto-apply makes this hotter because `apply_run()`
performs several mutations before its flush. Wrap each sector in `async with db.begin_nested()`,
the idiom already used for the savepoint-isolated dose fingerprint lookup. This is a
pre-existing defect, in scope because the design depends on per-sector isolation working.

**All-sectors-failed must not report success.** The per-sector `except` means a farm where
every sector errors still logs a clean run — the hole `classify_per_farm_run` closed at the
farm level. `compute_all_for_farm` returns counts (`applied`, `skipped`, `no_candidate`,
`failed`); the job logs WARNING when `failed > 0` and increments the metric with
`result="error"`.

**Degenerate inputs.** Missing `last_reading_at` → stale → veto. No probe, tension-only
probe, too few readings, implausible envelope → absorbed by gate 0.

## Testing

TDD: a failing test per gate before the policy exists.

**Pure unit tests on `evaluate_auto_apply`** — table-driven, no fixtures, no DB:

- gate precedence: override-governed *and* stale reports `manual_override`, not `probe_stale`
- bootstrap exemption: Δ0.15 with `bounds_from_prior_calibration=False` applies; identical
  input with `True` gives `delta_exceeds_cap`
- **stale prior calibration**: `before` is a preset (the resolver ignored the old row), so the
  cap must NOT apply — the deadlock guard from the Amendment
- **customized profile that does not govern bounds**: `bounds_from_manual_override=False`, so
  the override gate must NOT fire — the second deadlock guard
- `method="envelope"` applies (guards against reinstating the cycles veto)
- delta of exactly 0.05 applies
- refill-only violation with FC steady blocks
- all-depths-flat gives `flatline`; one-depth-flat applies

**Service-level tests** against the test DB, each building its own farm subtree through the
existing fixtures rather than mutating the globally-seeded sector. These tests write
`is_customized` and soil bounds — precisely the local dev-DB corruption trap CLAUDE.md
documents, which breaks `test_ctx_mad_in_range`.

- flag off → `candidate` row, projection untouched (opt-out path unchanged)
- flag on, passing → `applied` row, prior `superseded`, projection upserted, audit row with
  `user_id IS NULL`
- **flag on, `is_customized=True` with soil FC/PWP set (resolved source `scp_override`) →
  nothing recorded and the flag still `True`** — the most important regression guard in this
  design
- flag on, `is_customized=True` with soil fields NULL (resolved source `plot_preset`) →
  applies, and the flag is still `True` afterwards
- flag on, a >90-day-old `probe_calibration` row + a far candidate → applies (not
  `delta_exceeds_cap`)
- flag on, every depth flatlined but a plausible pooled candidate → `flatline` (proves the
  gate, not gate 0)
- savepoint isolation: two sectors, first forced to raise, second still applies
- returned counts reflect `failed`

**API test:** `PUT /farms/{id}` toggles the flag; cross-tenant returns 404 through `Access`.

## Files touched

| File | Change |
|---|---|
| `backend/app/engine/calibration_policy.py` | new — pure policy |
| `backend/app/services/probe_calibration_service.py` | `compute_and_auto_apply`, `auto_apply` param, counts, savepoints |
| `backend/app/services/scheduler.py` | read per-farm flag, summary log |
| `backend/app/models/farm.py` | `calibration_auto_apply` column |
| `backend/app/schemas/farm.py` | field on `FarmUpdate` / `FarmOut` |
| `backend/app/metrics.py` | `calibration_auto_apply_total` |
| `backend/alembic/versions/` | one autogenerated migration |
| `backend/tests/test_engine/` | pure policy tests |
| `backend/tests/test_api/` | service + farm-flag tests |

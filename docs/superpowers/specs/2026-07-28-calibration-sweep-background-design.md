# Background calibration sweep with polling — design

**Date:** 2026-07-28
**Status:** approved, not implemented
**Scope:** backend (one table, one migration, two endpoints, one worker job) + frontend (polling in one component)
**Fixes:** the synchronous sweep shipped in `docs/superpowers/specs/2026-07-28-calibration-auto-apply-ui-design.md`, which fails in production

## Problem — measured, not theorised

The first real use of `POST /farms/{farm_id}/calibration-sweep` on Herdade do Esporão produced
three browser 500s. Production logs showed the backend returned **200 every time**:

```
18:01:02  POST …/calibration-sweep  status 200  duration_ms 293180   (4.9 min)
18:04:27  POST …/calibration-sweep  status 200  duration_ms 443486   (7.4 min)
18:07:49  POST …/calibration-sweep  status 200  duration_ms 574027   (9.6 min)
```

while the frontend container logged:

```
Failed to proxy http://backend:8000/api/v1/farms/…/calibration-sweep
Error: socket hang up   code: 'ECONNRESET'
```

The Next.js rewrite proxy gives up around five minutes and returns 500; the sweep completes
afterwards and its result is discarded. There were **zero** backend errors — the work succeeded,
only the reply was lost.

Two further facts from that data:

- **Durations grew across the three attempts** (4.9 → 7.4 → 9.6 min) because the clicks ran
  concurrently against the same database. There is no lock around the manual sweep; the final
  whole-branch review of the previous cycle flagged that as a deferred Minor, and this is it
  happening.
- **Local reproduction was clean** — a 77-sector farm swept in seconds against seeded data. The
  cost is real production reading volume in the `probe_reading` hypertable, roughly six reading
  queries per sector. No query tuning turns 5–10 minutes into a safe margin under a ~5-minute
  proxy ceiling.

The Monday scheduler job is **unaffected**: it runs in-process in the worker with no proxy in
front of it. Only the on-demand button is broken.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Executor | The **worker**, fed by a Redis queue | The worker already runs this exact sweep on Mondays, and long jobs belong there. Production runs `uvicorn --workers 4`, so an in-process task would tie up one of four API processes and be orphaned by any redeploy. |
| Feedback | **Live progress** (`sector N of M`) | A bare spinner for ten minutes is indistinguishable from broken — the exact failure just experienced. The per-sector row update that progress needs also gives staleness detection for free. |
| Concurrency | **Per-farm mutex**, parallel across farms | Closes the observed pile-up. Different farms can sweep at once; the Monday job takes the same per-farm lock, so manual and scheduled can never collide on one farm. |
| Result storage | New table, `outcomes` as JSONB | Mirrors the existing `ProviderIngestionRun` run-telemetry pattern. Blocked sectors persist no row of their own, so their reasons exist nowhere else and must be durable. |

## Rejected alternatives

- **Keep it synchronous and optimise.** `build_quality` adds two queries per sector on top of the
  calibrator's ~4, so a shared reading load might roughly halve the cost — 5–10 min becomes
  2.5–5 min, still at or over the ceiling. It would ship a fix that still fails on the largest farm.
- **Batch from the UI** (sweep ~10 sectors per request). No background infrastructure, but it
  changes the endpoint contract *and* the UX, and a mid-way failure leaves a farm half-swept.
- **Raise the proxy timeout / bypass Next for this route.** Quickest, but leaves a ten-minute
  request holding a connection, still spins the button with no abort, and does nothing about
  concurrent clicks.
- **Add a one-off APScheduler job from the API.** Does not work: the scheduler lives in the worker
  with an in-memory jobstore, so the API cannot reach it without a shared jobstore.

## Architecture

```
Browser ── POST /farms/{id}/calibration-sweep ──▶ API (uvicorn ×4)
             access.farm() → ownership
             reclaim any stale non-terminal row for this farm
             INSERT calibration_sweep_run (status='queued')   ← partial unique index
             LPUSH calibration_sweep_queue {run_id}             makes duplicates impossible
             202 { run_id, status: 'queued' }

Worker (APScheduler, every 10s) ── _drain_calibration_sweep_queue
             RPOP → run_id
             per-farm Redis lock held for the whole sweep
             status='running', started_at, sectors_total
             per sector: sweep → UPDATE sectors_done, heartbeat_at, counts
             finish → status, finished_at, outcomes JSONB, duration logged

Browser ── GET /calibration-sweep-runs/{run_id} every 2s ──▶ progress, then result
```

**Two guards, distinct jobs.** A **partial unique index** on
`calibration_sweep_run(farm_id) WHERE status IN ('queued','running')` makes duplicate *requests*
impossible even across the four API processes: the second INSERT raises, the endpoint catches it
and returns 409. A **per-farm Redis lock** (`JobLock("calibration_sweep:{farm_id}")`) guards
actual *execution*, and the Monday job takes the same lock, so the two paths cannot collide on one
farm.

The 409 body carries the existing `run_id`, so clicking again attaches to the running sweep
instead of failing uselessly.

Ordering is deliberate: the row is inserted **before** the queue push. A row with no queue entry
goes stale and is recoverable; a queue entry with no row is not.

## Data model

One new table, mirroring `ProviderIngestionRun`:

```python
class CalibrationSweepRun(Base):
    __tablename__ = "calibration_sweep_run"

    id: str                        # UUID pk
    farm_id: str                   # FK farm.id ON DELETE CASCADE, indexed
    triggered_by_id: str | None    # FK user.id ON DELETE SET NULL — null if ever scheduled
    status: str                    # queued | running | success | partial | failure | stale
    auto_apply: bool               # the flag the sweep honoured, captured at queue time
    sectors_total: int | None      # known once running
    sectors_done: int = 0
    applied: int = 0
    skipped: int = 0
    no_candidate: int = 0
    candidates: int = 0
    failed: int = 0
    outcomes: list[dict] | None    # JSONB: the SectorSweepOutcome list, once finished
    error: str | None              # message when status == 'failure'
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
```

Plus the partial unique index above, and an index on `(farm_id, queued_at DESC)` for lookups.

`heartbeat_at` is written on every sector — which progress needs anyway — so **staleness costs
nothing extra**. A non-terminal row is presumed dead when its `heartbeat_at` (or `queued_at`, for
a row never picked up) is older than `SWEEP_STALE_MINUTES = 30`, defined in the new
`services/calibration_sweep_service.py`. That threshold is comfortably
above the ~10-minute worst case observed, and 30 minutes of a wedged farm is the blast radius.

`stale` is **terminal**, so it drops out of the unique index predicate — which is what guarantees
a dead run can never lock a farm out permanently.

`outcomes` as JSONB rather than a child table: it is written once, read whole, and never queried
field-wise.

## API

| Endpoint | Behaviour |
|---|---|
| `POST /farms/{farm_id}/calibration-sweep` | **202** `{run_id, status}`. Keeps `@limiter.limit("3/minute")` and `access.farm()`. **409** `{detail, run_id}` when a run is already queued/running. Reclaims a stale row (marks it `stale`) then proceeds. |
| `GET /calibration-sweep-runs/{run_id}` | The poll target. Returns the row plus `sectors_total`/`sectors_done`, counts, and `outcomes` once terminal. Ownership resolved through the run's farm, so cross-tenant and unknown ids both **404**. **Deliberately NOT rate-limited** — a 2s poll over a ten-minute sweep is ~300 requests, and any `@limiter.limit` here would 429 the client mid-sweep. `limiter` is opt-in per endpoint, so omitting the decorator is sufficient; do not add one. |

The synchronous behaviour is **replaced, not kept alongside** — it is demonstrably broken in
production, and two paths would drift.

Both live in `api/v1/auto_calibration.py` with inline response models, following that module's
existing convention.

## Worker

New job in `services/scheduler.py`:

```
_drain_calibration_sweep_queue   IntervalTrigger(seconds=10)   id="calibration_sweep_drain"
```

A 10-second interval is cheap (a single Redis `RPOP` when idle) and bounds pickup latency to
~10s against a multi-minute job. It drains one run per tick — a second queued run for a
*different* farm is picked up on the next tick, which keeps concurrency naturally low without a
worker pool.

**When the per-farm lock is already held** — the Monday job is sweeping that same farm, or a
previous drain tick is still working it — the drain job **pushes the run id back onto the queue
and leaves the row `queued`**, retrying on a later tick. It must not mark the run failed: the
request was valid and the farm is merely busy. The row's `queued_at` staleness threshold is the
backstop, so a run that can never acquire the lock eventually goes `stale` rather than cycling
forever.

On worker **startup**, any `running` row whose heartbeat is already cold is marked `stale`
(crash recovery), so a redeploy mid-sweep cannot leave a farm wedged until the threshold expires.

`ProbeCalibrationService.compute_all_for_farm` gains an optional
`on_sector_done: Callable[[int, CalibrationSweepCounts], Awaitable[None]] | None` invoked after
each sector's savepoint releases. The scheduler's Monday path passes `None` and is otherwise
unchanged. This keeps the sweep ignorant of run rows — it reports progress, it does not persist it.

## Frontend

`FarmCalibrationControls` gains a polling lifecycle. The mechanics matter more than the markup,
because this codebase has documented `useEffect` race problems:

- **Recursive `setTimeout`** (2s), not `setInterval`, so a slow poll cannot stack on itself.
- **Timer in a ref**, cleared in a `useEffect` cleanup — unmounting mid-sweep must not `setState`
  on a dead component. Navigating away during a ten-minute sweep is the normal case.
- **Stop conditions:** terminal status, unmount, or a **poll cap** of 20 minutes, after which the
  strip reads *"ainda a correr — recarregue a página mais tarde"* rather than spinning forever.
- **Progress:** `a calibrar… 34/77` plus a bar from `sectors_done`/`sectors_total`.
- **Terminal:** the existing tally and per-sector disclosure, unchanged. `stale` renders
  *"interrompida — tente novamente"*; `partial` shows the tally with the `failed` count visible.
- **409:** read `run_id` from the error body and attach to that run.

`ApiError` gains an optional third constructor argument carrying the parsed response body.
`request()` already parses the body and discards everything but `detail`; this closes that gap
additively, and the 409 `run_id` needs it.

## Error handling

Every non-terminal state has a defined exit — a wedged farm is worse than a failed sweep:

| Situation | Outcome |
|---|---|
| Worker restarts mid-sweep | Heartbeat goes cold → `stale`; also marked `stale` on worker startup |
| Redis flushed, queue entry lost | Row stays `queued`; staleness measured from `queued_at` → `stale` |
| `LPUSH` fails after the INSERT | Row goes `stale` (deliberate ordering, see Architecture) |
| One sector raises | Already savepoint-isolated → counted `failed`, sweep continues, terminal status `partial` |
| Whole sweep raises | `failure` + `error` text; lock released; row terminal |
| Two clicks race across API processes | Second INSERT violates the partial unique index → 409 with the first run's id |
| Migration not yet applied | The endpoint 500s. Migrate **before** swapping images |

## Observability

On completion the worker logs total duration and per-sector average, and a new histogram
`irrigai_calibration_sweep_duration_seconds` records it. Nobody knew this took five minutes until
production said so; the same blindness would hide a regression. Terminal statuses increment
`irrigai_calibration_sweep_total{status}`.

## Testing

**Service:** `on_sector_done` fires once per sector after its savepoint releases; a per-sector
failure yields `partial` not `failure`; the Monday path with `on_sector_done=None` is unchanged.

**API:** 202 shape; a duplicate returns 409 carrying the run id — asserted by attempting **two
inserts**, exercising the unique index rather than only the pre-check; a stale row is reclaimed
and a new run starts; the GET 404s cross-tenant and on unknown ids; `outcomes` is absent while
running and present when terminal.

**Worker:** the drain job picks up a queued run and completes it; startup marks cold `running`
rows `stale`; the per-farm lock prevents a second concurrent execution.

**Frontend:** polling stops on terminal status; polling stops on unmount with **no state update
after** (the race guard); progress renders from the counts; a 409 attaches to the existing run;
the poll cap surfaces the recharge message.

Test-DB discipline as established: `tests/test_engine/` builds its own subtree and rolls back;
`tests/test_api/` commits and cleans up in `try/finally`; never touch the globally-seeded sector.

## Out of scope

- **Having the Monday scheduler write `CalibrationSweepRun` rows.** It would let the strip show
  "última: seg 03/08 · aplicadas 12" for free and is tempting, but it changes the scheduler path
  and is not needed to fix the button. Follow-up once this is proven.
- Per-sector cost optimisation (a shared reading load between `build_quality` and
  `compute_sector_calibration`). Worth doing, independent of this.
- A general job-queue abstraction. One queue, one consumer, one job type — YAGNI.
- Cancelling a running sweep.

## Files touched

| File | Change |
|---|---|
| `backend/app/models/calibration_sweep_run.py` | new model |
| `backend/app/models/__init__.py` | export it |
| `backend/alembic/versions/<rev>_calibration_sweep_run.py` | new, autogenerated (table + partial unique index) |
| `backend/app/services/probe_calibration_service.py` | `on_sector_done` hook |
| `backend/app/services/calibration_sweep_service.py` | new — queue push/drain, run-row lifecycle, staleness |
| `backend/app/services/scheduler.py` | drain job, startup stale reclaim, per-farm lock on the Monday path |
| `backend/app/api/v1/auto_calibration.py` | POST returns 202; new GET; inline models |
| `backend/app/metrics.py` | duration histogram + status counter |
| `backend/tests/…` | service, API and worker tests |
| `frontend/src/lib/api.ts` | `ApiError` body; `calibrationApi.sweepFarm` returns the run; `calibrationApi.sweepRun(runId)` |
| `frontend/src/types/index.ts` | `CalibrationSweepRun` type |
| `frontend/src/components/farms/FarmCalibrationControls.tsx` | polling lifecycle, progress, stale/partial rendering |
| `CLAUDE.md` | replace the "Synchronous: tens of seconds" note with the real numbers and the new contract |

Deploy: `alembic upgrade head` **before** swapping, then `--build backend worker frontend` — all
three, since the worker gains the drain job and the frontend the polling.

# Calibration auto-apply — farm-list UI and manual sweep

**Date:** 2026-07-28
**Status:** approved, not implemented
**Scope:** backend (one endpoint, one service field) + frontend (one component, client, types)
**Builds on:** `docs/superpowers/specs/2026-07-28-calibration-auto-apply-design.md` (deployed 2026-07-28, commit `3d22b5a`)

## Problem

`Farm.calibration_auto_apply` shipped as an ops flag with **no UI**, toggled by `PUT /farms/{id}`
or SQL, and the sweep only runs on the scheduler's Monday 04:00 UTC trigger. Two consequences:

- Enabling a farm requires a token and a curl, so the deliberate one-farm-at-a-time rollout is
  gated behind terminal access.
- After enabling, you wait up to seven days to learn what the sweep does. On 2026-07-28 (a
  Tuesday) the next run was 132 hours away.

This adds both controls to the farm-selection dashboard, where farms are already listed.

**Supersedes** the "no UI surface by design — it's an ops flag" note in CLAUDE.md; that line
must be updated when this lands.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Who sees it | Anyone who can see the farm | The list already shows only farms you own (admin sees all via the `AccessController` bypass), and `PUT /farms/{id}` already enforces ownership. An admin-only gate would need a new `GET /auth/me` plus a current-user store — the frontend has no role check anywhere today and cannot know the caller's role. |
| What the trigger does | Runs the identical sweep the scheduler runs, honouring the farm's flag | One code path. Flag on → applies; flag off → records candidates only. The button therefore cannot do something Monday wouldn't, and pressing it *is* how you preview Monday. |
| Feedback | Counts **plus** per-sector detail | Blocked sectors persist no DB row by design, so their reasons exist only in worker logs. Surfacing them in the response is the difference between "ignoradas 40" and knowing which and why. |
| Placement | Footer strip below the card body | The whole `FarmCard` is wrapped in a `<Link>`; a `<button>` inside an `<a>` is invalid HTML and breaks keyboard/screen-reader behaviour. The strip is a sibling of the link, and gives the result list room to expand in place. |

## Rejected alternatives

- **A separate collect-outcomes service method**, leaving `compute_all_for_farm` untouched:
  duplicates the sweep loop into two paths that can drift, which forfeits the "button can never
  do what the scheduler wouldn't" property.
- **Counts-only response**, with the UI reconstructing detail from
  `GET /sectors/{id}/calibration-runs`: applied sectors are recoverable that way, but blocked
  ones write no row, so exactly the cases you need explained stay invisible.
- **A dry-run/preview mode**: a third code path through the sweep. The flag-off path already
  *is* a non-destructive preview (it records candidates and changes no bounds), so a separate
  preview would duplicate it.

## Backend

### New endpoint

```
POST /api/v1/farms/{farm_id}/calibration-sweep
```

Modelled on the existing `POST /farms/{farm_id}/recommendations/generate`: synchronous,
`@limiter.limit("3/minute")`, guarded by `access.farm(farm_id)` so a missing *or* cross-tenant
farm both return 404 (no existence leak). Lives in `api/v1/auto_calibration.py` beside the other
calibration endpoints, so it inherits the router's global `get_current_user` dependency.

Passes `auto_apply=farm.calibration_auto_apply` — the endpoint reads the flag, never overrides it.

Response:

```jsonc
{
  "auto_apply": true,              // the flag the sweep honoured, echoed for UI certainty
  "counts": {
    "applied": 12, "skipped": 40, "no_candidate": 25, "candidates": 0, "failed": 0
  },
  "outcomes": [
    {
      "sector_id": "…", "sector_name": "Talhão A3",
      "reason": "applied",         // stable machine value; PT label is the frontend's job
      "applied": true,
      "fc_before": 0.16, "fc_candidate": 0.31,
      "refill_before": 0.07, "refill_candidate": 0.20,
      "method": "envelope",
      "before_source": "plot_preset"
    }
  ]
}
```

`fc_candidate` / `refill_candidate` are populated for **blocked** sectors too, not just applied
ones — "we measured 0,44 but the cap blocked the move" is the most useful thing the UI can say
about a `delta_exceeds_cap`. All four are null for `no_candidate` (nothing was computed).

Response schemas are defined **inline in `api/v1/auto_calibration.py`**, following that module's
existing convention — `ProbeCalibrationOut` and `CalibrationHistoryOut` already live there, and
there is no `app/schemas/auto_calibration.py`.

`applied` is redundant with `reason == "applied"`; it is kept as client convenience so the UI
branches on a boolean rather than string-matching a machine value.

Audited as `probe_calibration_sweep_triggered` on entity `farm`, with the counts and
`auto_apply` in `after_data`. This gives manual farm-wide runs a real `user_id`, distinguishing
them from the scheduler's `user_id=NULL` rows.

### Service change

`CalibrationSweepCounts` gains one field:

```python
outcomes: list[SectorSweepOutcome] = field(default_factory=list)
```

where `SectorSweepOutcome` is a new small dataclass in the same module pairing the sector's
identity with the existing `AutoApplyOutcome` data:

```python
@dataclass(frozen=True)
class SectorSweepOutcome:
    sector_id: str
    sector_name: str
    reason: str
    applied: bool
    fc_before: float | None
    fc_candidate: float | None
    refill_before: float | None
    refill_candidate: float | None
    method: str | None
    before_source: str | None
```

`compute_all_for_farm` appends one per sector, in the same place it already increments counters
— **after the savepoint releases**, preserving the existing rule that a rolled-back sector leaves
no trace claiming success. `AutoApplyOutcome` already carries `before_fc`, `before_refill`,
`before_source`, `candidate_fc`, `candidate_refill` and `method`, so nothing new is computed;
the sector name comes from the `Sector` rows the sweep already loads.

Failed sectors append an outcome with `reason="error"` so the count and the list agree. The
flag-off path appends `reason="candidate"`.

`"error"` and `"candidate"` are **sweep-level** reasons, not gate decisions — they describe
outcomes the policy never sees (an exception, and the flag-off path that bypasses the gate
entirely). They must **not** be added to `calibration_policy.py`'s `REASON_*` constants, which
are the gate's vocabulary and are asserted against in the pure tests.

**Unchanged:** the gate, `apply_run`, `build_quality`, the flag semantics, the scheduler's
per-sector logging, and `PUT /farms/{id}` (which already accepts the flag — the toggle needs no
new endpoint).

## Frontend

### New component

`components/farms/FarmCalibrationControls.tsx` — the footer strip, owning the toggle, the
trigger, pending state, and the result disclosure.

A new `components/farms/` directory rather than `components/dashboard/`: that directory is
farm-*detail*-scoped (imported only by `/farms/[farmId]` pages), so a farms-list control there
would blur the boundary.

`FarmCard` in `app/page.tsx` becomes a wrapper `<div>` holding the existing `<Link>` plus the
strip as a sibling. `app/page.tsx` is already 430 lines, so the logic lives in the component and
the page change is the wrapper plus a two-line insertion.

### Behaviour

- **Toggle** writes through `PUT /farms/{id}`, optimistically, reverting on failure. Switching it
  on shows a one-line note that Monday 04:00 UTC will now apply bounds on this farm.
- **Trigger** is disabled while running and while the toggle write is in flight. A single
  in-flight guard prevents double submission.
- **Confirmation only when the flag is ON.** That is the case that mutates live soil bounds. With
  the flag off the sweep records candidates and changes nothing, so a dialog there would be
  friction protecting nothing.
- **Results render in place:** the tally always; per-sector rows behind a disclosure. Applied rows
  read `CC 0,16 → 0,31`; blocked rows show the PT reason and, where a candidate exists,
  `0,16 ⇢ 0,44`. Numbers go through `formatDecimal` (pt-PT comma decimals, the project
  convention).
- **Reason labels live in the frontend**, mirroring how crop-stage `key`s are handled — the API
  returns the stable machine value:

  | reason | label |
  |---|---|
  | `applied` | aplicada |
  | `manual_override` | ajuste manual do solo |
  | `probe_stale` | sonda sem dados recentes |
  | `flatline` | sinal plano |
  | `delta_exceeds_cap` | variação demasiado grande |
  | `no_candidate` | sem dados suficientes |
  | `candidate` | registada como candidata |
  | `error` | erro |

### Client and types

- `farmsApi.setCalibrationAutoApply(id, enabled)` and `farmsApi.runCalibrationSweep(id)`.
  A dedicated toggle method rather than widening `FarmCreate`, since `farmsApi.update` is typed
  `Partial<FarmCreate>` and the flag must not be settable at farm creation.
- `Farm` gains `calibration_auto_apply: boolean`.
- New `CalibrationSweepResponse` / `SectorSweepOutcome` types.

## Error handling

- **Slow request.** On Innoliva's 77 sectors the sweep runs tens of seconds — inherent, since it
  is the work the Monday job does, and the precedent endpoint has the same property. The UI shows
  a pending state throughout; no client-side timeout is introduced, so the browser's default
  applies. If this proves too slow in practice the follow-up is a background job with polling,
  deliberately **out of scope** here.
- **Partial failure.** Per-sector failures are already savepoint-isolated and counted as `failed`;
  the endpoint returns 200 with those sectors listed as `reason="error"`. A farm-wide failure
  returns 500 with the message, matching the precedent endpoint's `Engine error:` shape.
- **Rate limit** returns 429; the UI surfaces it as "demasiados pedidos, tente novamente".
- **Toggle failure** reverts the optimistic switch and shows the error; no sweep is started.

## Testing

**Backend** (`tests/test_api/`):
- ownership: cross-tenant and unknown farm both 404
- flag OFF → response `auto_apply: false`, outcomes all `reason="candidate"`, no
  `probe_calibration` projection written
- flag ON with a calibratable sector → `applied` outcome carrying `fc_before`/`fc_candidate`
- a blocked sector reports its reason **and** its candidate values (the payload's whole point)
- an audit row exists with a non-null `user_id`

**Frontend** (Vitest):
- toggle round-trip and revert-on-failure
- confirm dialog appears only when the flag is on
- trigger disabled while running
- a blocked outcome renders its PT label and the `⇢` candidate value
- counts render with pt-PT decimals

Test-DB discipline as established: own farm subtree per test, `db.flush()`, `await db.rollback()`,
never the globally-seeded sector.

## Out of scope

- Admin-only gating (needs `GET /auth/me` + a current-user store).
- A background/async sweep with polling.
- Any change to the gate, thresholds, or flag semantics.
- Per-sector manual apply from this surface — `POST /sectors/{id}/auto-calibration/run` and the
  calibration-run history already cover that.

## Files touched

| File | Change |
|---|---|
| `backend/app/api/v1/auto_calibration.py` | new `POST /farms/{farm_id}/calibration-sweep` + its inline response schemas |
| `backend/app/services/probe_calibration_service.py` | `SectorSweepOutcome`, `outcomes` on the counts |
| `backend/tests/test_api/test_calibration_sweep.py` | new endpoint tests |
| `frontend/src/components/farms/FarmCalibrationControls.tsx` | new — the footer strip |
| `frontend/src/app/page.tsx` | wrap `FarmCard`, mount the strip |
| `frontend/src/lib/api.ts` | two client methods |
| `frontend/src/types/index.ts` | `Farm.calibration_auto_apply`, sweep types |
| `frontend/src/components/farms/__tests__/FarmCalibrationControls.test.tsx` | new |
| `CLAUDE.md` | replace the "no UI surface by design" note |

No migration. Deploy needs `--build backend frontend`; `worker` is untouched by this change.

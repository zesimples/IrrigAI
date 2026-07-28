# Calibration auto-apply UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the per-farm calibration auto-apply toggle and a manual sweep trigger on the farm-selection dashboard, with per-sector feedback.

**Architecture:** The sweep already builds an `AutoApplyOutcome` per sector and discards it after logging; it now also collects a serialisable `SectorSweepOutcome` list on its return value. One new synchronous endpoint runs the *same* sweep the scheduler runs, honouring the farm's own flag, and returns counts plus those outcomes. A new footer-strip component on each farm card owns the toggle, the trigger and the result disclosure — mounted as a sibling of the card's `<Link>`, never inside it.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, slowapi; Next.js 14 App Router, React, TypeScript, Vitest + @testing-library/react, lucide-react.

**Spec:** `docs/superpowers/specs/2026-07-28-calibration-auto-apply-ui-design.md`

## Global Constraints

- Python: ruff, line-length 100, target py312. Rules E, F, I (isort), UP, B, SIM. ruff isort orders a from-import by type: CONSTANTS, then classes, then functions.
- TypeScript: ESLint, strict TS. Frontend user-facing copy is **European Portuguese**.
- All user-facing numbers use pt-PT formatting via `formatDecimal` from `@/lib/utils` (comma decimals). Input fields stay dot-based.
- `"error"` and `"candidate"` are **sweep-level** reasons describing outcomes the gate never sees. They must NOT be added to `calibration_policy.py`'s `REASON_*` constants, which are the gate's vocabulary and are asserted in the pure policy tests.
- The endpoint reads `farm.calibration_auto_apply` and passes it through. It must never override the flag — one code path, so the button cannot do something the Monday job wouldn't.
- No change to the gate, `apply_run`, `build_quality`, thresholds, or flag semantics. No migration.
- Counters, logs and now outcome collection happen only AFTER the per-sector savepoint releases. A rolled-back sector must never appear as applied.
- DB tests build their own farm subtree with `db.flush()` and end with `await db.rollback()` — never commit, never touch the globally-seeded sector (that breaks `tests/test_engine/test_context_loading.py::test_ctx_mad_in_range` until someone re-seeds).
- No `window.confirm` / `alert` anywhere — browser modal dialogs block the page and are untestable in jsdom. The confirm step is an inline two-state button.

## Environment

- Backend container mounts `./backend` as `/app`; host edits are live, no rebuild. Container paths are relative to `/app`, which IS the repo's `backend/` directory.
- Backend tests: `docker compose exec -T backend python -m pytest <path> -v`
- Backend lint: `docker compose exec -T backend ruff check <paths>`
- Frontend has **no source mount even in dev** — but Vitest runs on the host: `cd frontend && npm run test:run`
- Frontend lint/types: `cd frontend && npm run lint && npx tsc --noEmit`
- Current backend baseline: **720 passed, 10 skipped**. Current frontend baseline: **83 passed**.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/probe_calibration_service.py` | `SectorSweepOutcome` dataclass; `outcomes` on `CalibrationSweepCounts`; collection in the sweep |
| `backend/app/api/v1/auto_calibration.py` | `POST /farms/{farm_id}/calibration-sweep` + its inline Pydantic response models |
| `backend/tests/test_engine/test_calibration_auto_apply_db.py` | extend: outcomes collected on each path |
| `backend/tests/test_api/test_calibration_sweep.py` | **new** — endpoint ownership, flag routing, payload shape, audit |
| `frontend/src/types/index.ts` | `Farm.calibration_auto_apply`; sweep response types |
| `frontend/src/lib/api.ts` | `farmsApi.setCalibrationAutoApply`, `calibrationApi.sweepFarm` |
| `frontend/src/components/farms/FarmCalibrationControls.tsx` | **new** — the footer strip |
| `frontend/src/components/farms/__tests__/FarmCalibrationControls.test.tsx` | **new** |
| `frontend/src/app/page.tsx` | wrap `FarmCard`'s `<Link>`, mount the strip as a sibling |
| `CLAUDE.md` | replace the "no UI surface by design" note |

## Deviations from the spec, decided while planning

1. **The sweep client method goes on `calibrationApi`, not `farmsApi`.** `lib/api.ts` already has a `calibrationApi` block and the endpoint lives in `api/v1/auto_calibration.py`; grouping by resource beats grouping by URL prefix. The toggle stays on `farmsApi` because it is a farm update.
2. **The confirm step is an inline two-state button, not a modal or `window.confirm`.** There is no reusable confirm-dialog component in this codebase (`OverrideModal` is bespoke to overrides), and `window.confirm` blocks the page. Clicking *correr* on an enabled farm turns the button into *confirmar* with a *cancelar* beside it.

---

### Task 1: Collect per-sector outcomes in the sweep

**Files:**
- Modify: `backend/app/services/probe_calibration_service.py:28-36` (`CalibrationSweepCounts`), `:342-396` (`compute_all_for_farm`), `:398-404` (`_count_failure`), `:406-445` (`_record_outcome`)
- Test: `backend/tests/test_engine/test_calibration_auto_apply_db.py` (append)

**Interfaces:**
- Consumes: the existing `AutoApplyOutcome` (fields `decision`, `before_fc`, `before_refill`, `before_source`, `candidate_fc`, `candidate_refill`, `method`, plus `.apply` and `.reason` properties) and `CalibrationSweepCounts` (int fields `applied`, `skipped`, `no_candidate`, `candidates`, `failed`).
- Produces:
  - `SectorSweepOutcome` — frozen dataclass: `sector_id: str`, `sector_name: str`, `reason: str`, `applied: bool`, `fc_before/fc_candidate/refill_before/refill_candidate: float | None`, `method: str | None`, `before_source: str | None`.
  - `CalibrationSweepCounts.outcomes: list[SectorSweepOutcome]` — one entry per sector on every path, ordered as swept.
  - `_count_failure(sector_id, sector_name, counts)` and `_record_outcome(sector_id, sector_name, outcome, counts)` — both gain a `sector_name` parameter.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_engine/test_calibration_auto_apply_db.py`:

```python
@pytest.mark.asyncio
async def test_sweep_collects_one_outcome_per_sector_when_applying(db: AsyncSession):
    sector_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)
    counts = await ProbeCalibrationService().compute_all_for_farm(
        farm_id, db, auto_apply=True
    )

    assert counts.applied == 1
    assert len(counts.outcomes) == 1
    o = counts.outcomes[0]
    assert o.sector_id == sector_id
    assert o.sector_name == "AA Sector"
    assert o.reason == "applied"
    assert o.applied is True
    # The clamped preset it replaced, and the measured value it moved to.
    assert o.fc_before == pytest.approx(0.16)
    assert o.fc_candidate is not None and 0.43 <= o.fc_candidate <= 0.46
    assert o.before_source == "plot_preset"
    assert o.method == "envelope"
    await db.rollback()


@pytest.mark.asyncio
async def test_blocked_sector_outcome_carries_its_candidate_values(db: AsyncSession):
    """The payload's whole point: 'we measured X but the gate blocked the move'."""
    sector_id, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True,
                                            last_reading_age_h=200.0)
    counts = await ProbeCalibrationService().compute_all_for_farm(
        farm_id, db, auto_apply=True
    )

    assert counts.skipped == 1
    assert len(counts.outcomes) == 1
    o = counts.outcomes[0]
    assert o.sector_id == sector_id
    assert o.reason == "probe_stale"
    assert o.applied is False
    assert o.fc_before == pytest.approx(0.16)
    assert o.fc_candidate is not None  # measured, then withheld
    await db.rollback()


@pytest.mark.asyncio
async def test_flag_off_sweep_reports_candidate_outcomes(db: AsyncSession):
    _, farm_id = await _make_sector(db, vwc=0.44, auto_apply=False)
    counts = await ProbeCalibrationService().compute_all_for_farm(
        farm_id, db, auto_apply=False
    )

    assert counts.candidates == 1
    assert [o.reason for o in counts.outcomes] == ["candidate"]
    assert counts.outcomes[0].applied is False
    await db.rollback()


@pytest.mark.asyncio
async def test_failed_sector_appears_in_outcomes_as_error(db: AsyncSession):
    """counts.failed and the outcome list must not disagree."""
    from sqlalchemy import select

    _, farm_id = await _make_sector(db, vwc=0.44, auto_apply=True)
    plot = (await db.execute(select(Plot).where(Plot.farm_id == farm_id))).scalar_one()
    bad = Sector(plot_id=plot.id, name="Boom", crop_type="almond")
    db.add(bad)
    await db.flush()

    svc = ProbeCalibrationService()
    original = svc.compute_and_auto_apply

    async def flaky(sector_id, session):
        if sector_id == str(bad.id):
            raise RuntimeError("boom")
        return await original(sector_id, session)

    svc.compute_and_auto_apply = flaky
    counts = await svc.compute_all_for_farm(farm_id, db, auto_apply=True)

    assert counts.failed == 1
    assert len(counts.outcomes) == 2
    errored = [o for o in counts.outcomes if o.reason == "error"]
    assert len(errored) == 1
    assert errored[0].sector_name == "Boom"
    assert errored[0].applied is False
    await db.rollback()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_engine/test_calibration_auto_apply_db.py -v -k "outcome or candidate_outcomes"`
Expected: FAIL with `AttributeError: 'CalibrationSweepCounts' object has no attribute 'outcomes'`

- [ ] **Step 3: Add the dataclass and the field**

In `backend/app/services/probe_calibration_service.py`, change the `dataclasses` import to include `field`:

```python
from dataclasses import dataclass, field
```

Add `SectorSweepOutcome` immediately **before** `CalibrationSweepCounts` (it is referenced by the annotation):

```python
@dataclass(frozen=True)
class SectorSweepOutcome:
    """One sector's sweep result, in a shape the API can serialise.

    Pairs the sector's identity with the numbers already carried by
    AutoApplyOutcome. `fc_candidate` / `refill_candidate` are populated for
    BLOCKED sectors too, not just applied ones: "we measured 0.44 but the cap
    blocked the move from 0.16" is the most useful thing the UI can say about a
    delta_exceeds_cap, and blocked runs persist no row to look it up from.
    """

    sector_id: str
    sector_name: str
    reason: str
    applied: bool
    fc_before: float | None = None
    fc_candidate: float | None = None
    refill_before: float | None = None
    refill_candidate: float | None = None
    method: str | None = None
    before_source: str | None = None
```

Then add the field to `CalibrationSweepCounts` (after `failed`):

```python
    outcomes: list[SectorSweepOutcome] = field(default_factory=list)
```

- [ ] **Step 4: Thread the sector name through and collect**

Replace the loop body in `compute_all_for_farm` (the `for sector in sectors:` block) with:

```python
        counts = CalibrationSweepCounts()
        for sector in sectors:
            sector_id = str(sector.id)
            sector_name = sector.name
            outcome: AutoApplyOutcome | None = None
            recorded_candidate = False
            try:
                async with db.begin_nested():
                    if auto_apply:
                        outcome = await self.compute_and_auto_apply(sector_id, db)
                    else:
                        recorded = await self.compute_and_record(
                            sector_id, db, apply=False, source="scheduled"
                        )
                        recorded_candidate = recorded is not None
            except Exception:
                self._count_failure(sector_id, sector_name, counts)
                continue

            # Savepoint released — the work below can no longer be rolled back, so
            # counters, logs and outcomes describe what actually persisted.
            if auto_apply and outcome is not None:
                self._record_outcome(sector_id, sector_name, outcome, counts)
            elif recorded_candidate:
                counts.candidates += 1
                counts.outcomes.append(
                    SectorSweepOutcome(
                        sector_id=sector_id,
                        sector_name=sector_name,
                        reason="candidate",
                        applied=False,
                    )
                )
        return counts
```

- [ ] **Step 5: Record outcomes in the two helpers**

Change `_count_failure`'s signature and body:

```python
    @staticmethod
    def _count_failure(
        sector_id: str, sector_name: str, counts: CalibrationSweepCounts
    ) -> None:
        from app.metrics import calibration_auto_apply_total

        counts.failed += 1
        calibration_auto_apply_total.labels("error", "exception", "none").inc()
        logger.exception("Probe calibration failed for sector %s", sector_id)
        counts.outcomes.append(
            SectorSweepOutcome(
                sector_id=sector_id,
                sector_name=sector_name,
                reason="error",
                applied=False,
            )
        )
```

Change `_record_outcome`'s signature to `(sector_id: str, sector_name: str, outcome: AutoApplyOutcome, counts: CalibrationSweepCounts)`, leave its existing tally/log branches exactly as they are, and append once at the very end of the method (after the if/elif/else, so every branch is covered by one append):

```python
        counts.outcomes.append(
            SectorSweepOutcome(
                sector_id=sector_id,
                sector_name=sector_name,
                reason=reason,
                applied=outcome.apply,
                fc_before=outcome.before_fc,
                fc_candidate=outcome.candidate_fc,
                refill_before=outcome.before_refill,
                refill_candidate=outcome.candidate_refill,
                method=outcome.method,
                before_source=outcome.before_source,
            )
        )
```

- [ ] **Step 6: Run the new tests**

Run: `docker compose exec -T backend python -m pytest tests/test_engine/test_calibration_auto_apply_db.py -v`
Expected: PASS — 20 passed (16 existing + 4 new)

- [ ] **Step 7: Confirm the scheduler and ops script still work**

Run: `docker compose exec -T backend python -m pytest tests/test_engine/ tests/test_api/ -q`
Expected: PASS, no regressions. `_calibration_sweep_for_farm` reads only the int counters and is unaffected; `scripts/recompute_probe_calibration.py` reads `counts.candidates`/`counts.failed` and is unaffected.

- [ ] **Step 8: Lint**

Run: `docker compose exec -T backend ruff check app/services/probe_calibration_service.py tests/test_engine/test_calibration_auto_apply_db.py`
Expected: All checks passed

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/probe_calibration_service.py \
        backend/tests/test_engine/test_calibration_auto_apply_db.py
git commit -m "feat(calibration): collect per-sector outcomes in the farm sweep

Blocked sectors persist no row, so their reasons existed only in worker
logs. The sweep already computed the values — it now returns them, with
candidate values kept for blocked sectors too."
```

---

### Task 2: The manual sweep endpoint

**Files:**
- Modify: `backend/app/api/v1/auto_calibration.py` (add models near the existing `ProbeCalibrationOut` at `:73`, and the route at the end of the file)
- Test: `backend/tests/test_api/test_calibration_sweep.py` (new)

**Interfaces:**
- Consumes: `CalibrationSweepCounts` + `SectorSweepOutcome` from Task 1; the pre-existing `Access` dependency, `limiter`, and `audit`.
- Produces: `POST /api/v1/farms/{farm_id}/calibration-sweep` returning `CalibrationSweepOut` — `{ auto_apply: bool, counts: SweepCountsOut, outcomes: list[SectorSweepOutcomeOut] }`.

Note: `api/v1/auto_calibration.py` defines its response models **inline** (see `ProbeCalibrationOut`, `CalibrationHistoryOut`); there is no `app/schemas/auto_calibration.py`. Follow the file's convention.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api/test_calibration_sweep.py`:

```python
"""POST /farms/{farm_id}/calibration-sweep — the manual farm-wide sweep."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Farm, Plot, Probe, ProbeDepth, ProbeReading, Sector, User

from .conftest import delete_farm_subtree

# The email the authenticated `client` fixture logs in as — the farm must be owned
# by this user or access.farm() correctly 404s.
_OWNER_EMAIL = "you@irrigai.dev"


async def _farm_with_calibratable_sector(
    db: AsyncSession, *, auto_apply: bool, stale_hours: float = 1.0
) -> tuple[str, str]:
    """Farm→Plot→Sector→Probe→depth + 60 hourly VWC readings near 0.44.

    The plot carries the sandy_loam preset (FC 0.16) that clamps a probe sitting
    near 0.44 — the bug auto-apply exists to fix.
    """
    owner = (
        await db.execute(select(User).where(User.email == _OWNER_EMAIL))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(email=_OWNER_EMAIL, name="API Test Fixture", hashed_password="x")
        db.add(owner)
        await db.flush()

    stamp = datetime.now(UTC).timestamp()
    farm = Farm(name=f"Sweep Farm {stamp}", owner_id=owner.id,
                calibration_auto_apply=auto_apply)
    db.add(farm)
    await db.flush()
    plot = Plot(farm_id=farm.id, name="P", soil_texture="sandy_loam",
                field_capacity=0.16, wilting_point=0.07)
    db.add(plot)
    await db.flush()
    sector = Sector(plot_id=plot.id, name="Talhão A3", crop_type="almond")
    db.add(sector)
    await db.flush()
    probe = Probe(sector_id=sector.id, external_id=f"sweep-{stamp}",
                  last_reading_at=datetime.now(UTC) - timedelta(hours=stale_hours))
    db.add(probe)
    await db.flush()
    depth = ProbeDepth(probe_id=probe.id, depth_cm=20, sensor_type="soil_moisture")
    db.add(depth)
    await db.flush()

    base = datetime.now(UTC) - timedelta(hours=59)
    lo, hi = 0.41, 0.455
    for i in range(60):
        phase = i % 24
        frac = phase / 12
        tri = frac if frac <= 1 else (2 - frac)
        v = round(lo + (hi - lo) * tri, 4)
        db.add(ProbeReading(probe_depth_id=depth.id, timestamp=base + timedelta(hours=i),
                            raw_value=v, calibrated_value=v,
                            unit="vwc_m3m3", quality_flag="ok"))
    await db.flush()
    return str(farm.id), str(sector.id)


@pytest.mark.asyncio
async def test_unknown_farm_returns_404(client):
    resp = await client.post(
        "/api/v1/farms/00000000-0000-0000-0000-000000000000/calibration-sweep"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sweep_with_flag_on_applies_and_reports_the_transition(client, db: AsyncSession):
    farm_id, sector_id = await _farm_with_calibratable_sector(db, auto_apply=True)
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 200
        body = resp.json()

        assert body["auto_apply"] is True
        assert body["counts"]["applied"] == 1
        assert len(body["outcomes"]) == 1
        o = body["outcomes"][0]
        assert o["sector_id"] == sector_id
        assert o["sector_name"] == "Talhão A3"
        assert o["reason"] == "applied"
        assert o["applied"] is True
        assert o["fc_before"] == pytest.approx(0.16)
        assert 0.43 <= o["fc_candidate"] <= 0.46
    finally:
        await delete_farm_subtree(db, farm_id)
        await db.commit()


@pytest.mark.asyncio
async def test_sweep_with_flag_off_records_candidates_only(client, db: AsyncSession):
    from app.models import ProbeCalibration

    farm_id, sector_id = await _farm_with_calibratable_sector(db, auto_apply=False)
    await db.commit()
    try:
        resp = await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")
        assert resp.status_code == 200
        body = resp.json()

        assert body["auto_apply"] is False
        assert body["counts"]["candidates"] == 1
        assert body["counts"]["applied"] == 0
        assert [o["reason"] for o in body["outcomes"]] == ["candidate"]

        # Nothing may reach the projection the engine reads.
        projection = (await db.execute(
            select(ProbeCalibration).where(ProbeCalibration.sector_id == sector_id)
        )).scalar_one_or_none()
        assert projection is None
    finally:
        await delete_farm_subtree(db, farm_id)
        await db.commit()


@pytest.mark.asyncio
async def test_blocked_sector_reports_reason_and_candidate(client, db: AsyncSession):
    farm_id, _ = await _farm_with_calibratable_sector(
        db, auto_apply=True, stale_hours=200.0
    )
    await db.commit()
    try:
        body = (await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")).json()

        assert body["counts"]["skipped"] == 1
        o = body["outcomes"][0]
        assert o["reason"] == "probe_stale"
        assert o["applied"] is False
        assert o["fc_candidate"] is not None   # measured, then withheld
    finally:
        await delete_farm_subtree(db, farm_id)
        await db.commit()


@pytest.mark.asyncio
async def test_sweep_is_audited_with_the_triggering_user(client, db: AsyncSession):
    farm_id, _ = await _farm_with_calibratable_sector(db, auto_apply=True)
    await db.commit()
    try:
        await client.post(f"/api/v1/farms/{farm_id}/calibration-sweep")

        entries = (await db.execute(
            select(AuditLog).where(
                AuditLog.action == "probe_calibration_sweep_triggered",
                AuditLog.entity_id == farm_id,
            )
        )).scalars().all()
        assert len(entries) == 1
        # Unlike the scheduler's user_id=NULL rows, a manual sweep names its user.
        assert entries[0].user_id is not None
        assert entries[0].after_data["auto_apply"] is True
    finally:
        await delete_farm_subtree(db, farm_id)
        await db.commit()
```

Fixture notes: `tests/test_api/conftest.py` provides `client` (authenticated as `you@irrigai.dev`) and `db` (a direct `AsyncSession` for arranging data), plus the `delete_farm_subtree(db, farm_id)` helper. These tests **commit** their arranged farm — unlike the `test_engine` DB tests — because the request goes through the app's own session and cannot see uncommitted rows; hence the `try/finally` teardown on every test. Verify `delete_farm_subtree` covers `probe_calibration`, `probe_calibration_run` and `audit_log` rows for the farm; if it does not, delete those explicitly in the `finally` before calling it, and note the gap in your report.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_api/test_calibration_sweep.py -v`
Expected: FAIL — 404/405 on an unregistered route (the unknown-farm test may pass vacuously; the others must fail)

- [ ] **Step 3: Add the response models**

In `backend/app/api/v1/auto_calibration.py`, after the existing `ProbeCalibrationOut` class:

```python
class SectorSweepOutcomeOut(BaseModel):
    sector_id: str
    sector_name: str
    reason: str
    applied: bool
    fc_before: float | None = None
    fc_candidate: float | None = None
    refill_before: float | None = None
    refill_candidate: float | None = None
    method: str | None = None
    before_source: str | None = None


class SweepCountsOut(BaseModel):
    applied: int
    skipped: int
    no_candidate: int
    candidates: int
    failed: int


class CalibrationSweepOut(BaseModel):
    # Echoed so the UI never has to infer which mode ran.
    auto_apply: bool
    counts: SweepCountsOut
    outcomes: list[SectorSweepOutcomeOut]
```

- [ ] **Step 4: Add the route**

Append to `backend/app/api/v1/auto_calibration.py`. Add `Request` to the `fastapi` import and `from app.limiter import limiter` to the imports:

```python
@router.post("/farms/{farm_id}/calibration-sweep", response_model=CalibrationSweepOut)
@limiter.limit("3/minute")
async def run_farm_calibration_sweep(
    request: Request,
    farm_id: str,
    access: Access,
    db: AsyncSession = Depends(get_db),
):
    """Run the weekly calibration sweep for one farm, now, honouring its flag.

    Deliberately the SAME path the scheduler runs: with the farm's
    `calibration_auto_apply` off this records candidates and changes no bounds,
    which makes the button a safe preview of what Monday 04:00 UTC will do. The
    endpoint never overrides the flag.

    Synchronous, like POST /farms/{id}/recommendations/generate — on a large farm
    (77 sectors at Innoliva) this runs for tens of seconds.
    """
    farm = await access.farm(farm_id)
    auto_apply = bool(farm.calibration_auto_apply)
    try:
        counts = await _calib_service.compute_all_for_farm(
            farm_id, db, auto_apply=auto_apply
        )
    except Exception as exc:
        raise HTTPException(500, detail=f"Calibration sweep error: {exc}") from exc

    await audit.log(
        "probe_calibration_sweep_triggered",
        "farm",
        farm_id,
        db,
        user_id=str(access.current_user.id),
        after_data={
            "auto_apply": auto_apply,
            "applied": counts.applied,
            "skipped": counts.skipped,
            "no_candidate": counts.no_candidate,
            "candidates": counts.candidates,
            "failed": counts.failed,
        },
    )
    await db.commit()

    return CalibrationSweepOut(
        auto_apply=auto_apply,
        counts=SweepCountsOut(
            applied=counts.applied,
            skipped=counts.skipped,
            no_candidate=counts.no_candidate,
            candidates=counts.candidates,
            failed=counts.failed,
        ),
        outcomes=[
            SectorSweepOutcomeOut(
                sector_id=o.sector_id,
                sector_name=o.sector_name,
                reason=o.reason,
                applied=o.applied,
                fc_before=o.fc_before,
                fc_candidate=o.fc_candidate,
                refill_before=o.refill_before,
                refill_candidate=o.refill_candidate,
                method=o.method,
                before_source=o.before_source,
            )
            for o in counts.outcomes
        ],
    )
```

- [ ] **Step 5: Run the tests**

Run: `docker compose exec -T backend python -m pytest tests/test_api/test_calibration_sweep.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Full backend suite**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: PASS — 729 passed, 10 skipped (720 baseline + 4 from Task 1 + 5 here)

- [ ] **Step 7: Lint**

Run: `docker compose exec -T backend ruff check app/api/v1/auto_calibration.py tests/test_api/test_calibration_sweep.py`
Expected: All checks passed (the router's pre-existing FastAPI `B008` convention is project-wide and not gated in CI)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/auto_calibration.py backend/tests/test_api/test_calibration_sweep.py
git commit -m "feat(calibration): POST /farms/{id}/calibration-sweep

Runs the scheduler's own sweep on demand, honouring the farm's flag, so
the button cannot do something Monday wouldn't. Audited with the real
user, unlike the scheduler's user_id=NULL rows."
```

---

### Task 3: The footer-strip component

**Files:**
- Modify: `frontend/src/types/index.ts`, `frontend/src/lib/api.ts`
- Create: `frontend/src/components/farms/FarmCalibrationControls.tsx`
- Test: `frontend/src/components/farms/__tests__/FarmCalibrationControls.test.tsx`

**Interfaces:**
- Consumes: the Task 2 endpoint; the pre-existing `useToast()` hook (`toast(title, { variant, description })` with variants `success` / `info` / `error`), `ApiError` (fields `status`, `detail`), and `formatDecimal(value, digits)` from `@/lib/utils`.
- Produces: `<FarmCalibrationControls farmId={string} initialEnabled={boolean} />`; `farmsApi.setCalibrationAutoApply(id, enabled)`; `calibrationApi.sweepFarm(id)`; types `CalibrationSweepResponse`, `SectorSweepOutcome`, `SweepCounts`; `Farm.calibration_auto_apply`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/farms/__tests__/FarmCalibrationControls.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { FarmCalibrationControls } from "../FarmCalibrationControls";

const toast = vi.fn();

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast, toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  farmsApi: { setCalibrationAutoApply: vi.fn() },
  calibrationApi: { sweepFarm: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { farmsApi, calibrationApi, ApiError } from "@/lib/api";

const mockToggle = farmsApi.setCalibrationAutoApply as ReturnType<typeof vi.fn>;
const mockSweep = calibrationApi.sweepFarm as ReturnType<typeof vi.fn>;

const sweep = (over: Record<string, unknown> = {}) => ({
  auto_apply: true,
  counts: { applied: 1, skipped: 1, no_candidate: 0, candidates: 0, failed: 0 },
  outcomes: [
    {
      sector_id: "s1", sector_name: "Talhão A3", reason: "applied", applied: true,
      fc_before: 0.16, fc_candidate: 0.31, refill_before: 0.07,
      refill_candidate: 0.2, method: "envelope", before_source: "plot_preset",
    },
    {
      sector_id: "s2", sector_name: "Talhão B1", reason: "delta_exceeds_cap",
      applied: false, fc_before: 0.16, fc_candidate: 0.44, refill_before: 0.07,
      refill_candidate: 0.2, method: "envelope", before_source: "plot_preset",
    },
  ],
  ...over,
});

describe("FarmCalibrationControls", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reflects the initial flag state on the switch", () => {
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("turns the flag on and warns that Monday will apply bounds", async () => {
    mockToggle.mockResolvedValue({ calibration_auto_apply: true });
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(mockToggle).toHaveBeenCalledWith("f1", true));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/segunda-feira/i)).toBeInTheDocument();
  });

  it("reverts the switch when the toggle write fails", async () => {
    mockToggle.mockRejectedValue(new ApiError(500, "boom"));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false"),
    );
    expect(toast).toHaveBeenCalledWith(
      expect.stringMatching(/não foi possível/i),
      expect.objectContaining({ variant: "error" }),
    );
    expect(mockSweep).not.toHaveBeenCalled();
  });

  it("asks for confirmation before sweeping an ENABLED farm", async () => {
    mockSweep.mockResolvedValue(sweep());
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    // First click only arms the confirm — nothing has run yet.
    expect(mockSweep).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /cancelar/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /confirmar/i }));
    await waitFor(() => expect(mockSweep).toHaveBeenCalledWith("f1"));
  });

  it("cancelling the confirm runs nothing", () => {
    render(<FarmCalibrationControls farmId="f1" initialEnabled />);
    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));
    expect(mockSweep).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /correr/i })).toBeInTheDocument();
  });

  it("sweeps a DISABLED farm immediately — nothing to protect", async () => {
    mockSweep.mockResolvedValue(sweep({ auto_apply: false }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() => expect(mockSweep).toHaveBeenCalledWith("f1"));
  });

  it("renders the tally and per-sector detail, blocked rows included", async () => {
    mockSweep.mockResolvedValue(sweep({ auto_apply: false }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() => expect(screen.getByText(/aplicadas 1/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /detalhe/i }));

    expect(screen.getByText("Talhão A3")).toBeInTheDocument();
    expect(screen.getByText(/16 → 31/)).toBeInTheDocument();
    // A blocked sector shows WHY and what it measured — the payload's whole point.
    expect(screen.getByText("Talhão B1")).toBeInTheDocument();
    expect(screen.getByText(/variação demasiado grande/i)).toBeInTheDocument();
    expect(screen.getByText(/16 ⇢ 44/)).toBeInTheDocument();
  });

  it("disables the trigger while a sweep is in flight", async () => {
    let resolve!: (v: unknown) => void;
    mockSweep.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /a calibrar/i })).toBeDisabled(),
    );

    resolve(sweep({ auto_apply: false }));
    await waitFor(() => expect(screen.getByText(/aplicadas 1/i)).toBeInTheDocument());
  });

  it("explains a rate-limit rejection", async () => {
    mockSweep.mockRejectedValue(new ApiError(429, "rate limited"));
    render(<FarmCalibrationControls farmId="f1" initialEnabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: /correr/i }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringMatching(/demasiados pedidos/i),
        expect.objectContaining({ variant: "error" }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/farms/__tests__/FarmCalibrationControls.test.tsx`
Expected: FAIL — cannot resolve `../FarmCalibrationControls`

- [ ] **Step 3: Add the types**

In `frontend/src/types/index.ts`, add to `interface Farm` (after `is_archived`):

```ts
  calibration_auto_apply: boolean;
```

and add near the other calibration types:

```ts
export interface SectorSweepOutcome {
  sector_id: string;
  sector_name: string;
  /** Stable machine value; the PT label lives in the UI. */
  reason: string;
  applied: boolean;
  fc_before: number | null;
  /** Populated for blocked sectors too — what was measured but withheld. */
  fc_candidate: number | null;
  refill_before: number | null;
  refill_candidate: number | null;
  method: string | null;
  before_source: string | null;
}

export interface SweepCounts {
  applied: number;
  skipped: number;
  no_candidate: number;
  candidates: number;
  failed: number;
}

export interface CalibrationSweepResponse {
  auto_apply: boolean;
  counts: SweepCounts;
  outcomes: SectorSweepOutcome[];
}
```

- [ ] **Step 4: Add the client methods**

In `frontend/src/lib/api.ts`, add `CalibrationSweepResponse` to the type import block. Add to the `farmsApi` object:

```ts
  setCalibrationAutoApply: (id: string, enabled: boolean) =>
    put<Farm>(`/farms/${id}`, { calibration_auto_apply: enabled }),
```

and to the `calibrationApi` object:

```ts
  sweepFarm: (farmId: string) =>
    post<CalibrationSweepResponse>(`/farms/${farmId}/calibration-sweep`),
```

The sweep sits on `calibrationApi` (not `farmsApi`) to match where the endpoint lives and how the client already groups calibration calls. The toggle is a farm update, so it stays on `farmsApi` — as a dedicated method rather than widening `FarmCreate`, since the flag must not be settable at creation.

- [ ] **Step 5: Write the component**

Create `frontend/src/components/farms/FarmCalibrationControls.tsx`:

```tsx
"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { ApiError, calibrationApi, farmsApi } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { formatDecimal } from "@/lib/utils";
import type { CalibrationSweepResponse, SectorSweepOutcome } from "@/types";

/** Machine reasons come from the backend; these labels are display-only, the
 *  same split used for crop-stage keys. */
const REASON_LABELS: Record<string, string> = {
  applied: "aplicada",
  manual_override: "ajuste manual do solo",
  probe_stale: "sonda sem dados recentes",
  flatline: "sinal plano",
  delta_exceeds_cap: "variação demasiado grande",
  no_candidate: "sem dados suficientes",
  candidate: "registada como candidata",
  error: "erro",
};

/** m³/m³ → vol% for display, pt-PT formatted. */
function vol(v: number | null): string | null {
  return v == null ? null : formatDecimal(v * 100, 0);
}

function OutcomeRow({ o }: { o: SectorSweepOutcome }) {
  const before = vol(o.fc_before);
  const candidate = vol(o.fc_candidate);
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-[12px] text-ink-2 truncate">{o.sector_name}</span>
      <span className="font-mono text-[10.5px] text-ink-3 shrink-0">
        {o.applied && before != null && candidate != null
          ? `${before} → ${candidate} vol%`
          : REASON_LABELS[o.reason] ?? o.reason}
        {/* A blocked sector still reports what it measured: the gate withheld a
            real value, which reads very differently from "no data". */}
        {!o.applied && before != null && candidate != null
          ? ` · ${before} ⇢ ${candidate} vol%`
          : ""}
      </span>
    </div>
  );
}

interface Props {
  farmId: string;
  initialEnabled: boolean;
}

/**
 * Per-farm calibration auto-apply toggle plus an on-demand sweep.
 *
 * The sweep runs the SAME path the Monday 04:00 UTC job runs and honours this
 * farm's flag, so with the toggle off it is a safe preview: candidates are
 * recorded and no soil bound moves.
 */
export function FarmCalibrationControls({ farmId, initialEnabled }: Props) {
  const { toast } = useToast();
  const [enabled, setEnabled] = useState(initialEnabled);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<CalibrationSweepResponse | null>(null);
  const [showDetail, setShowDetail] = useState(false);

  async function handleToggle() {
    const next = !enabled;
    setEnabled(next);           // optimistic
    setSaving(true);
    try {
      await farmsApi.setCalibrationAutoApply(farmId, next);
    } catch {
      setEnabled(!next);        // revert
      toast("Não foi possível alterar a calibração automática", {
        variant: "error",
        description: "Tente novamente.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function runSweep() {
    setConfirming(false);
    setRunning(true);
    try {
      const r = await calibrationApi.sweepFarm(farmId);
      setResult(r);
      toast(r.auto_apply ? "Calibração aplicada" : "Candidatas registadas", {
        variant: "success",
        description: r.auto_apply
          ? `${r.counts.applied} aplicadas · ${r.counts.skipped} ignoradas`
          : `${r.counts.candidates} candidatas · sem alterações aos limites`,
      });
    } catch (e) {
      const rateLimited = e instanceof ApiError && e.status === 429;
      toast(
        rateLimited ? "Demasiados pedidos" : "A calibração falhou",
        {
          variant: "error",
          description: rateLimited
            ? "Aguarde um minuto e tente novamente."
            : e instanceof ApiError
              ? e.detail
              : "Erro inesperado.",
        },
      );
    } finally {
      setRunning(false);
    }
  }

  // Only an enabled farm can have its live bounds changed by this button.
  function handleTriggerClick() {
    if (enabled) setConfirming(true);
    else void runSweep();
  }

  const c = result?.counts;

  return (
    <div className="border-t border-rule-soft px-6 py-2.5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Calibração automática"
            disabled={saving}
            onClick={handleToggle}
            className={`relative h-[18px] w-8 rounded-full transition-colors disabled:opacity-40 ${
              enabled ? "bg-olive" : "bg-rule"
            }`}
          >
            <span
              className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-paper transition-[left] ${
                enabled ? "left-[16px]" : "left-[2px]"
              }`}
            />
          </button>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-3">
            calibração automática
          </span>
        </div>

        {confirming ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void runSweep()}
              className="rounded-md border border-rule bg-paper px-2.5 py-1 text-[11.5px] text-ink-2"
            >
              confirmar
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-[11.5px] text-ink-3 underline"
            >
              cancelar
            </button>
          </div>
        ) : (
          <button
            type="button"
            disabled={running}
            onClick={handleTriggerClick}
            className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-paper px-2.5 py-1 text-[11.5px] text-ink-2 hover:bg-paper-in disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`h-3 w-3 ${running ? "animate-spin" : ""}`} />
            {running ? "a calibrar…" : "correr"}
          </button>
        )}
      </div>

      {enabled && (
        <p className="mt-1.5 text-[11px] text-ink-3">
          Ativa: segunda-feira às 04:00 UTC os limites deste campo podem ser
          atualizados automaticamente.
        </p>
      )}

      {c && (
        <div className="mt-2">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[10.5px] text-ink-3">
              aplicadas {c.applied} · ignoradas {c.skipped} · sem dados{" "}
              {c.no_candidate}
              {c.candidates ? ` · candidatas ${c.candidates}` : ""}
              {c.failed ? ` · erros ${c.failed}` : ""}
            </span>
            {result!.outcomes.length > 0 && (
              <button
                type="button"
                onClick={() => setShowDetail((s) => !s)}
                className="text-[11px] text-ink-3 underline shrink-0"
              >
                detalhe
              </button>
            )}
          </div>
          {showDetail && (
            <div className="mt-1 divide-y divide-rule-soft">
              {result!.outcomes.map((o) => (
                <OutcomeRow key={o.sector_id} o={o} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npx vitest run src/components/farms/__tests__/FarmCalibrationControls.test.tsx`
Expected: PASS — 9 passed

- [ ] **Step 7: Lint and type-check**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/farms/FarmCalibrationControls.tsx \
        frontend/src/components/farms/__tests__/FarmCalibrationControls.test.tsx \
        frontend/src/lib/api.ts frontend/src/types/index.ts
git commit -m "feat(ui): per-farm calibration toggle and on-demand sweep strip

Confirm step only when the flag is on (the only case that moves live
bounds). Blocked sectors show their reason AND what was measured, since
they persist no row to look up."
```

---

### Task 4: Mount the strip on the farm card

**Files:**
- Modify: `frontend/src/app/page.tsx:132-146` (`FarmCard` opening) and `:227-231` (its closing)
- Test: `frontend/src/app/__tests__/page.farmCard.test.tsx` (new)

**Interfaces:**
- Consumes: `<FarmCalibrationControls farmId initialEnabled />` from Task 3; the existing `FarmData` shape whose `.farm` is a `Farm` (now carrying `calibration_auto_apply`).
- Produces: no new exports. `FarmCard` keeps its `{ fd, idx }` props.

**Why this is its own task:** the whole card is currently wrapped in `<Link>`. A `<button>` inside an `<a>` is invalid HTML — it breaks keyboard and screen-reader behaviour and clicks navigate away instead of toggling. The strip must be a *sibling* of the link, and that structural change is independently reviewable.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/__tests__/page.farmCard.test.tsx`:

```tsx
/**
 * Guards the one structural rule the card must keep: the calibration controls
 * are siblings of the navigation link, never nested inside it.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  farmsApi: { list: vi.fn(), dashboard: vi.fn(), setCalibrationAutoApply: vi.fn() },
  calibrationApi: { sweepFarm: vi.fn() },
  clearToken: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = "ApiError";
    }
  },
}));

import { FarmCard } from "../page";

// FarmCard indexes VERDICT_COLORS[fd.verdict] and reads moisture/lastSync/et0/
// cultures, so every FarmData field must be present — a partial object crashes
// on VERDICT_COLORS[undefined].accent rather than failing an assertion.
const fd = {
  farm: {
    id: "f1", name: "Herdade do Esporão", location_lat: null, location_lon: null,
    elevation_m: null, region: "Alentejo", timezone: "Europe/Lisbon",
    owner_id: "u1", is_archived: false, calibration_auto_apply: false,
    archived_at: null, created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  dashboard: null,
  irrigateCount: 0,
  totalSectors: 0,
  verdict: "ok" as const,
  verdictLabel: "Sem rega hoje",
  verdictWhy: "",
  moisture: 0.62,
  lastSync: "há 5 min",
  et0: 4.2,
  cultures: ["almond"],
} as unknown as Parameters<typeof FarmCard>[0]["fd"];

describe("FarmCard calibration controls", () => {
  it("renders the switch outside the navigation anchor", () => {
    render(<FarmCard fd={fd} idx={1} />);

    const sw = screen.getByRole("switch");
    expect(sw).toBeInTheDocument();
    // The invariant: no interactive control nested in the <a>.
    expect(sw.closest("a")).toBeNull();
    expect(screen.getByRole("button", { name: /correr/i }).closest("a")).toBeNull();
  });

  it("still links through to the farm", () => {
    render(<FarmCard fd={fd} idx={1} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/farms/f1");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/app/__tests__/page.farmCard.test.tsx`
Expected: FAIL — `FarmCard` is not exported from `../page`, and no switch is rendered

- [ ] **Step 3: Restructure `FarmCard`**

In `frontend/src/app/page.tsx`:

Add the import at the top with the other component imports:

```tsx
import { FarmCalibrationControls } from "@/components/farms/FarmCalibrationControls";
```

Change the function signature to export it (so it is directly testable without mounting the whole page):

```tsx
export function FarmCard({ fd, idx }: { fd: FarmData; idx: number }) {
```

Wrap the existing `<Link>` in a container and add the strip after it. The `<Link>`'s own `className` loses its border/rounding/background to the wrapper, so the two read as one card:

```tsx
  return (
    <div className="bg-card border border-rule rounded-[10px] overflow-hidden transition-shadow hover:shadow-[0_4px_18px_rgba(42,37,32,0.08)]">
      <Link
        href={`/farms/${fd.farm.id}`}
        className="group block relative p-[22px_24px] no-underline"
      >
        {/* ...existing card body unchanged... */}
      </Link>
      <FarmCalibrationControls
        farmId={fd.farm.id}
        initialEnabled={fd.farm.calibration_auto_apply}
      />
    </div>
  );
```

Keep every child of the `<Link>` exactly as it is — only the wrapper, the link's `className`, and the added sibling change.

- [ ] **Step 4: Run the test**

Run: `cd frontend && npx vitest run src/app/__tests__/page.farmCard.test.tsx`
Expected: PASS — 2 passed

- [ ] **Step 5: Full frontend suite**

Run: `cd frontend && npm run test:run`
Expected: PASS — 94 passed (83 baseline + 9 from Task 3 + 2 here)

- [ ] **Step 6: Lint, types, production build**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm run build`
Expected: all clean. The build matters: `app/page.tsx` is a client component and the new import must not break the App Router build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/page.tsx frontend/src/app/__tests__/page.farmCard.test.tsx
git commit -m "feat(ui): mount calibration controls on each farm card

The card's Link now wraps only the navigable body; the controls are a
sibling, because a button inside an anchor is invalid HTML and clicks
would navigate instead of toggling. Test guards that structure."
```

---

### Task 5: Correct the CLAUDE.md note

**Files:**
- Modify: `CLAUDE.md` (the **Calibration auto-apply** section, first paragraph)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Replace the no-UI claim**

The section currently says the flag is toggled via `PUT /farms/{farm_id}` with "**no UI surface by design** — it's an ops flag". That is now false. Replace that parenthetical with:

```markdown
(toggled from the **farm-selection dashboard** — each farm card carries a calibration strip with the on/off switch and a *correr* button that runs the sweep on demand; also still settable via `PUT /farms/{farm_id}`)
```

- [ ] **Step 2: Document the endpoint alongside the others**

Add a bullet to the same section, after the observability bullet:

```markdown
- **Manual sweep:** `POST /farms/{farm_id}/calibration-sweep` (`api/v1/auto_calibration.py`, `3/minute`) runs the scheduler's own sweep for one farm on demand and **honours that farm's flag** — with the flag off it records candidates and moves no bounds, so it doubles as a safe preview of what Monday will do. It returns the counts plus a `SectorSweepOutcome` per sector (reason, and `fc_before`/`fc_candidate` even for blocked sectors), which is how blocked reasons reach the UI at all — they persist no DB row. Audited as `probe_calibration_sweep_triggered` with the real `user_id`, unlike the scheduler's `user_id=NULL` rows. Synchronous: tens of seconds on Innoliva's 77 sectors.
```

- [ ] **Step 3: Add the cycle entry**

Immediately before the `**Open, roughly prioritized:**` heading:

```markdown
**Done in the 2026-07-28 calibration-UI cycle (Claude Code; no migration; deploy `--build backend frontend`, worker untouched):** farm-selection dashboard now carries a per-farm calibration strip (toggle + on-demand sweep + per-sector outcome detail), backed by `POST /farms/{farm_id}/calibration-sweep`. The sweep collects a `SectorSweepOutcome` per sector so blocked reasons and their withheld candidate values reach the UI instead of living only in worker logs. No role gate: the frontend has no current-user surface (there is no `GET /auth/me`), and `PUT /farms/{id}` already enforces ownership — recorded as out of scope in the spec.
```

- [ ] **Step 4: Verify no stale claim remains**

Run: `grep -n "no UI surface" CLAUDE.md`
Expected: no matches

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — calibration auto-apply now has a UI

Replaces the 'no UI surface by design' note, documents the manual sweep
endpoint, and records the cycle."
```

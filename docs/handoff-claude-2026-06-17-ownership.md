# Handoff to Claude — 2026-06-17 (Codex ownership enforcement pass)

Context: Follow-up to `docs/handoff-codex-2026-06-17.md`, specifically open item
#1: **Per-tenant ownership enforcement**. Authentication had already been added
router-wide; this pass added authorization checks so logged-in users cannot read
or mutate another user's farm resources by id.

## Done

### 1. Shared ownership access controller

Added `backend/app/access.py`.

It provides:
- `AccessController.farm(farm_id)`
- `plot(plot_id)`
- `sector(sector_id)`
- `probe(probe_id)`
- `recommendation(rec_id)`
- `irrigation_event(event_id)`
- `alert(alert_id)`
- `override(override_id)`
- `water_event(event_id)`
- `require_admin()`

Behavior:
- Admin users bypass tenant ownership checks.
- Non-admin users must own the farm chain via `farm.owner_id == current_user.id`.
- Missing resources and cross-tenant resources both return `404`, avoiding
  resource-existence leaks.

### 2. Wired ownership checks into API routers

Updated these routers to call the shared access controller before reading or
mutating tenant-owned resources:

- `backend/app/api/v1/plots.py`
- `backend/app/api/v1/sectors.py`
- `backend/app/api/v1/probes.py`
- `backend/app/api/v1/dashboard.py`
- `backend/app/api/v1/weather.py`
- `backend/app/api/v1/recommendations.py`
- `backend/app/api/v1/alerts.py`
- `backend/app/api/v1/irrigation.py`
- `backend/app/api/v1/crop_profiles.py`
- `backend/app/api/v1/gdd.py`
- `backend/app/api/v1/overrides.py`
- `backend/app/api/v1/auto_calibration.py`
- `backend/app/api/v1/flowmeter.py`
- `backend/app/api/v1/flowmeter_reference.py`
- `backend/app/api/v1/chat.py`
- `backend/app/api/v1/audit_log.py`

Notes:
- Global catalog endpoints (`crop-profile-templates`, `soil-presets`) remain
  readable by any authenticated user.
- `/audit-log` is now admin-only. The audit schema is global and not reliably
  tenant-filterable for every entity type, so admin-only is the conservative
  choice.
- `farm_chat` checks both the `farm_id` path parameter and optional
  `body.sector_id`.

### 3. Test coverage added/updated

Updated `backend/tests/test_api/test_auth_permissions.py` with regression cases
for:
- Cross-tenant dashboard read blocked.
- Cross-tenant nested resource traversal blocked:
  farm plots, plot, plot sectors, sector, sector probes, probe.
- Cross-tenant recommendation mutation blocked.
- Cross-tenant alert mutation blocked.
- Cross-tenant irrigation event mutation blocked.
- Audit log blocked for non-admin users.

Updated fixtures so data-focused tests authenticate as the seeded demo owner:
- `backend/tests/test_api/conftest.py` now uses `you@irrigai.dev`.
- `backend/tests/test_water_event_persistence.py` now uses `you@irrigai.dev`.
- `backend/tests/test_e2e/conftest.py` marks the seeded user as admin in-memory
  because the full E2E pipeline explicitly verifies global audit-log reads.

## Verification

Commands run in Docker:

```bash
docker compose exec -T backend pytest -q tests/test_api/test_auth_permissions.py --tb=short
# 25 passed

docker compose exec -T backend pytest -q tests/test_api --tb=short
# 63 passed

docker compose exec -T backend pytest -q --tb=short
# 444 passed, 10 skipped, 6 warnings
```

Other checks:

```bash
python3 -m compileall -q backend/app/access.py backend/app/api/v1 \
  backend/tests/test_api/conftest.py \
  backend/tests/test_api/test_auth_permissions.py \
  backend/tests/test_e2e/conftest.py \
  backend/tests/test_water_event_persistence.py

ruff check backend/app/access.py
# All checks passed

git diff --check
# clean
```

## Known caveats / do not redo

- Full touched-router Ruff still reports existing project-wide FastAPI `B008`
  warnings (`Depends(...)`, `Query(...)`, request body defaults). This pass did
  not attempt that broader lint refactor.
- Existing test warnings remain from async mocks / SQLAlchemy cancellation; not
  introduced by this pass.
- Unrelated untracked docs/design files were left alone.

## Suggested next item

Proceed to handoff item #2 from `docs/handoff-codex-2026-06-17.md`:
rate limiting on `/auth/*` and `/chat/*`.


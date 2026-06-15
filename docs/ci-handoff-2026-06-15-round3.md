# CI Handoff (round 3) — 2026-06-15

Follow-up to round 1/2. This round drove the **backend test suite to green**
and fixed the surrounding CI jobs. Net result: **5 of 6 CI jobs green**; the
E2E Playwright job (which had never actually run) is the only remaining red.

## CI status now

| Job | Status |
|-----|--------|
| Backend tests | ✅ **green** (397 passed, 10 skipped — was never green, 0/30 historically) |
| Migration integrity | ✅ green |
| Frontend lint | ✅ green |
| Frontend unit tests | ✅ green |
| Frontend build | ✅ green |
| E2E tests (Playwright) | ❌ red — see "Remaining" below |

## What made the backend suite green

Root problem: CI migrates a fresh DB but never seeded it; ~half the suite
assumes the canonical seed dataset, and the seeder couldn't bootstrap a fresh
DB. On top of that ~25 tests had drifted from the code.

### Infrastructure
- **`app/seed.py`**: get-or-create the `you@irrigai.dev` owner (was
  `scalar_one()` → `NoResultFound` on a fresh DB). `python -m app.seed` now
  bootstraps a clean DB. (3 call sites collapsed to one get-or-create.)
- **`.github/workflows/ci.yml`**: added `python -m app.seed` to the Backend
  tests job (between migrate and pytest).
- **`tests/conftest.py`**: minimal probe-seed fixture (idempotent) + **disabled
  the slowapi rate limiter in tests** (shared Redis counter tripped 429s late
  in the suite; no test asserts rate limiting).

### ⚠️ Product behaviour changes (please review — these affect the live app)
These were documented-but-missing behaviours that tests asserted:
1. **`create_sector`** now auto-materialises a `SectorCropProfile` from the
   crop type's system-default template (mirrors seed + the reset endpoint).
2. **`create_plot`** now inherits `field_capacity`/`wilting_point`/`soil_texture`
   from the chosen soil preset when not given; **`PlotCreate`/`PlotUpdate` now
   accept `soil_preset_id`** (it was silently dropped before).
3. **Recommendation `inputs_snapshot` now includes `kc`** (threaded a `kc`
   field through `EngineRecommendation` → snapshot).
4. **`list_farms`** now orders by `created_at desc` (stable newest-first paging).
5. **Flowmeter analytics** evaluates recency vs the **period end**, not
   `date.today()` (for live dashboards period_end == today, so no prod change;
   historical periods are now scored correctly).
6. **`OverrideRequest.override_reason`** is now optional (the handler already
   fell back to the legacy `notes` field).

### Test-only drift fixes
- Engine mocks/ctors updated for new fields: `distribution_uniformity`
  (dosage), `rainfall_effectiveness` (trigger), `elevation_m` (minimal_config).
- Trigger reason assertions now match the Portuguese messages.
- `test_context_builder` helper includes the new required fields
  (`probe_live`, `source_confidence`, `data_quality_explanation`).
- **E2E `client` fixture now authenticates** (overrides `get_current_user` to
  the seeded owner) — auth was added after these tests were written.
- `test_probes` `seed_probe_id` fixture now ensures a soil_moisture depth with
  recent VWC readings (seeded olive probes only record soil_tension, which the
  readings endpoint filters out).

Commits: `0c360a1` (backend green), plus `bc0ab7f`/`f196761`/`0aa2839` from
earlier rounds. Verified locally on a fresh migrate→seed→pytest DB: 397 passed.

## Remaining: E2E Playwright job (red)

**Important:** this job had **never run before** — it `needs: [backend-test]`,
which was always red, so it was always *skipped*. It is not a regression; it's
being exercised for the first time.

What I changed (commits `c53e3a2`, `bd74343`, `e50b29e`, `a6621ff`): seed the DB,
boot backend+frontend and run Playwright in a single step, capture server logs,
force IPv4 (`127.0.0.1`). Diagnosis from the captured logs:
- Frontend boots fine (`✓ Ready`).
- Backend `uvicorn` **intermittently** completes startup — one run logged
  `Application startup complete / Uvicorn running on 0.0.0.0:8000`, the next
  froze at `Waiting for application startup`. So the backgrounded uvicorn is
  being reaped/stalled mid-startup by the runner's process management. Flaky.
- `wait-on http://127.0.0.1:8000/health` then times out.

**Recommended fix (a proper effort, not a one-liner):** stop backgrounding bare
processes. Boot the stack via the repo's `docker compose` (services already
defined) or as a GitHub **service container** for the backend, so it has a real
lifecycle + healthcheck. Then the Playwright suite itself still needs validating
end-to-end (it has never passed in CI) — expect to fix app/auth-flow assumptions
once the stack boots reliably.

If you want E2E to stop blocking the overall CISP while that's sorted, add
`continue-on-error: true` to the `e2e` job (temporary) — but better to fix the
boot.

## Reproduce backend suite locally (CI-equivalent)

```bash
docker compose exec -T db psql -U irrigai -d postgres -c "CREATE DATABASE ci_local;"
docker compose exec -T -e DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@db:5432/ci_local backend alembic upgrade head
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://irrigai:irrigai_dev@db:5432/ci_local \
  -e DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@db:5432/ci_local \
  -e PROBE_PROVIDER=mock -e WEATHER_PROVIDER=mock -e LLM_PROVIDER=mock backend python -m app.seed
docker compose exec -T -e DATABASE_URL=postgresql+asyncpg://irrigai:irrigai_dev@db:5432/ci_local \
  -e DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@db:5432/ci_local \
  -e REDIS_URL=redis://redis:6379/0 -e PROBE_PROVIDER=mock -e WEATHER_PROVIDER=mock -e LLM_PROVIDER=mock \
  backend pytest -q -p no:randomly
```

## Untouched (still yours)
`backend/app/ai/assistant.py`, `probe_signal.py`, `prompt_templates.py`,
`backend/tests/test_ai/test_assistant.py` remain uncommitted in the working tree.
All backend numbers above were measured with those stashed (committed state).

# CI Handoff (round 2) — 2026-06-15

Follow-up to `docs/ci-handoff-2026-06-15.md` and `docs/ci-codex-report-2026-06-15.md`.

Investigated the remaining red Backend tests job. **The framing of "conftest
isolation" undersold it** — the real problem is structural and pre-existing.

## Headline

- **CI backend tests have never been green** — 0 successes in the last 30 runs on `main`.
- Root cause: **CI migrates a fresh DB but never seeds it**, and a large set of
  tests assume the canonical seed dataset exists. `pytest -x` was stopping at the
  first one (`test_adapters.py::test_ingestion_inserts_new_readings`,
  `errors=16`, "Probe 1044/4663 not found").
- The demo seeder `app.seed` **cannot bootstrap a fresh DB**: it requires a
  pre-existing `you@irrigai.dev` user (queried via `scalar_one()` at
  `backend/app/seed.py:512`, never created) → `NoResultFound`.

## What I did (committed)

Added a minimal, idempotent autouse seed fixture in `backend/tests/conftest.py`
(`seed_minimal_probe_data` / `_ensure_seed_probes`). It creates **only** the
probes the ingestion tests need — `1044/4663`, `1044/4664`, `1044/4667` — each
with depth rows (10/30/60/90) and a farm→plot→sector chain owned by a dedicated
fixture user (`seed-fixture@irrigai.test`), so empty-DB / per-user API tests are
unaffected. It's compatible with (and will be subsumed by) a future full-seed
approach: it get-or-creates, so if real seed data is present it no-ops.

**Verified on a fresh, CI-equivalent DB** (migrated, unseeded): the 27 previously
failing ingestion tests now pass (`tests/test_adapters.py`,
`tests/test_ingestion_run.py`, `tests/test_per_depth_freshness.py`).

> ⚠️ This fix alone does NOT make CI green. It clears the `-x` blocker layer and
> fixes the probe-level tests; the deeper layer below still fails.

## What remains (for Codex) — 30 failed + 69 errors

Full list: `docs/ci-remaining-failures-2026-06-15.txt`. Counts by file:

| Count | Type | File |
|------:|------|------|
| 11 | ERROR | tests/test_api/test_probes.py |
| 10 | ERROR | tests/test_engine/test_context_loading.py |
| 10 | ERROR | tests/test_api/test_recommendations.py |
|  8 | FAILED | tests/test_engine/test_dosage.py |
|  8 | ERROR | tests/test_engine/test_pipeline.py |
|  8 | ERROR | tests/test_api/test_dashboard.py |
|  7 | FAILED | tests/test_ai/test_context_builder.py |
|  6 | FAILED | tests/test_engine/test_minimal_config.py |
|  6 | ERROR | tests/test_e2e/test_scenarios.py |
|  5 | FAILED | tests/test_engine/test_trigger.py |
|  3 | ERROR | tests/test_water_event_persistence.py |
|  3 | ERROR | tests/test_e2e/test_full_pipeline.py |
|  3 | ERROR | tests/test_e2e/test_crop_profiles.py |
|  3 | ERROR | tests/test_anomaly/test_detector.py |
|  3 | ERROR | tests/test_agronomic_context.py |
|  2/1 | FAILED | tests/test_e2e/test_onboarding.py |
|  1 | FAILED | tests/test_flowmeter/test_analytics.py |
|  1 | FAILED | tests/test_e2e/test_scenarios.py |
|  1 | ERROR | tests/test_e2e/test_onboarding.py |

These all depend on the **full canonical seed dataset** — seed sectors, crop
profiles, irrigation systems, recommendations — not just probes. The `ERROR`s are
fixture/setup failures (data not present); the `FAILED`s are assertions that read
seed sectors (dosage/trigger/minimal_config/context-builder).

## Recommended fix (Codex's call — overlaps your domain)

The robust path to green is to **seed the canonical dataset in CI**:

1. Make `app.seed` fresh-DB-safe — get-or-create `you@irrigai.dev` instead of
   `scalar_one()` at `seed.py:512` (mirror the `agronomist` get-or-create just
   above it). Check the other `scalar_one()` uses at lines 1053 / 1605 too.
2. Add a seed step to the Backend tests job in `.github/workflows/ci.yml`,
   between "Run migrations" and "Run tests":
   ```yaml
   - name: Seed test data
     run: python -m app.seed
   ```
3. Resolve the **empty-vs-seeded tension**: some API/list tests assume an empty
   DB while engine/e2e tests want seed data. The autouse cleanup
   (`isolate_committed_db_rows`) deletes volatile tables but not farm/sector/probe.
   With full seed present, audit any count/exact-list assertions in `test_api/*`.

Once full seed is in place, my `seed_minimal_probe_data` fixture becomes a no-op
(safe to keep or remove).

## Reproduce CI locally

```bash
# fresh, CI-equivalent DB (no seed)
docker compose exec -T db psql -U irrigai -d postgres -c "CREATE DATABASE ci_local;"
docker compose exec -T -e DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@db:5432/ci_local \
  backend alembic upgrade head
docker compose exec -T \
  -e DATABASE_URL=postgresql+asyncpg://irrigai:irrigai_dev@db:5432/ci_local \
  -e DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@db:5432/ci_local \
  -e PROBE_PROVIDER=mock -e WEATHER_PROVIDER=mock -e LLM_PROVIDER=mock \
  backend pytest -q --tb=line -p no:randomly
```

## Note on the AI files

Still uncommitted (yours): `backend/app/ai/assistant.py`,
`backend/app/ai/probe_signal.py`, `backend/app/ai/prompt_templates.py`,
`backend/tests/test_ai/test_assistant.py`. The numbers above were measured with
those stashed (committed state), to mirror CI.

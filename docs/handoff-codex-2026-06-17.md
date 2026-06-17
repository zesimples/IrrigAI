# Handoff for Codex — 2026-06-17 (security/ops pass + app review)

Context: Claude Code session driven from an app-wide review. Two commits landed on
`main` this session. This doc lists what's **done** (don't redo) and what's
**open** (candidates to pick up), with enough detail to start cold.

> Coordination note: Claude and Codex run in parallel on this repo. **Re-read any
> file before editing** — it may have changed since this was written.

---

## ✅ Done — landed on `main`

### A. `fix(ai)` — farm-summary prompt gates on skip/defer (commit `9b0aa76`)
- **Problem:** `FARM_SUMMARY_PT`/`_EN` told the LLM to group sectors by
  `recommendation_action == "no_irrigation"` — a value the `RecommendationAction`
  enum never emits (`context_builder.py:279` passes the raw `skip`/`defer`). The
  "Sem necessidade"/"No action" grouping matched nothing.
- **Fix:** `backend/app/ai/prompt_templates.py` — 4 refs now `"skip"`/`"defer"`.
- **Test:** `test_farm_summary_prompt_gates_on_real_recommendation_actions` (pt/en).
- Closes the last latent instance of the `no_irrigation` phantom value.

### B. `feat(security/ops)` — 4 hardening items (commit `f57e895`)

1. **Authentication on every v1 endpoint.**
   - `backend/app/api/v1/router.py` includes every router with
     `dependencies=[Depends(get_current_user)]` **except `/auth`**. New routers
     inherit auth by default.
   - Was: only `/farms` enforced auth; `sectors/plots/probes/recommendations/chat/
     alerts/irrigation/dashboard/flowmeter/...` were reachable anonymously.
   - Test fixtures: `test_api/conftest.py` now has `client` (authed) +
     `noauth_client` (real auth, for `test_auth_permissions`). Data-test clients
     authenticate via a get-or-create `api-test-fixture@irrigai.test` user (works
     on both local demo-seed DB and CI fresh DB). Same override added to
     `test_flowmeter/conftest.py` and `test_water_event_persistence.py`.

2. **Mandatory production encryption key.**
   - `backend/app/config.py::check_production_security()` raises on startup when
     `DEBUG=false` and `ENCRYPTION_KEY` is unset (would derive field encryption
     from `SECRET_KEY`) or `SECRET_KEY` is the placeholder. Called from
     `main.py` lifespan and `worker.py::main()`. Documented in `.env.example`.

3. **Container healthchecks** (`docker-compose.yml`).
   - backend → `/health`; worker (no HTTP) → `python -m app.worker_health`, which
     reads a Redis scheduler heartbeat (`app/heartbeat.py`). nginx waits for
     backend `service_healthy` in `docker-compose.prod.yml`.

4. **Scheduler partial-failure observability** (`backend/app/services/scheduler.py`).
   - The 4 non-flowmeter jobs swallowed per-farm exceptions and always recorded
     `"success"` — a total outage looked healthy. Added `classify_per_farm_run`
     (success / partial_failure / failure), shared `_run_per_farm_job` helper,
     `scheduler_farm_failures_total` metric, WARNING summary, liveness heartbeat
     (startup + after every job).

**Verification:** backend suite `439 passed, 10 skipped`; ruff clean on touched
files; both compose files validate.

---

## 🔧 Open — candidates to pick up (priority order)

### 1. Per-tenant OWNERSHIP enforcement  — HIGH (direct follow-up to done #B1)
Authentication is enforced, but **any logged-in user can still read/write another
user's resources by id** outside `farms.py`. Only `farms.py` checks
`owner_id == current_user.id` (admin bypass). Need ownership checks across
`sectors/plots/probes/recommendations/irrigation/dashboard/alerts/flowmeter/...`,
walking `sector→plot→farm→owner_id`. Large (~15 routers); best as a shared
dependency (e.g. `require_farm_access(farm_id)` + resource-id resolvers). See
memory `api-auth-model.md`.

### 2. Rate limiting gaps — HIGH (security)
Only 2 endpoints are limited (`backend/app/limiter.py`, recommendations). Add
limits to `POST /auth/token`, `POST /auth/register`, and all `/chat/*` (LLM cost /
credential-stuffing exposure). Pattern already exists on recommendations.

### 3. E2E Playwright job — MEDIUM (CI)
Red/never-green on `main`, single spec, not required. Either stabilize the
stack-boot + make it a required check, or stop treating it as a gate. See memory
`ci-main-red-since-june11`. (Backend suite is green.)

### 4. Frontend data-fetching & coverage — MEDIUM
- `useEffect` fetch waterfalls + race conditions on rapid param changes
  (`ProbeReadingsInline.tsx`); `Promise.all` all-or-nothing in
  `FlowmeterDashboard.tsx`. Adopt React Query/SWR or at least `Promise.allSettled`
  + `AbortController`.
- Thin Vitest coverage on core components (`SectorAnalysis`, `ProbeReadingsInline`,
  flowmeter dashboard).
- Large components (`sectors/[sectorId]/page.tsx` ~700 lines), heavy inline
  styles, duplicated bullet-parsing logic between `SectorAnalysis.tsx` and
  `ProbeReadingsInline.tsx`.

### 5. Engine-correctness findings — UNVERIFIED, MEDIUM
Surfaced by review subagents but **not line-verified** — confirm before acting:
- Zero-TAW division / nonsensical `pct_depleted` (`engine/trigger.py`, pipeline
  entry) when `root_depth` or `(FC-PWP)` ≈ 0.
- Probe unit validation: VWC accepted even when `unit != vwc_m3m3`
  (`engine/probe_interpreter.py`).
- Ingestion dedup idempotency on partial/crashed runs (`services/ingestion.py`).
- Uncalibrated-probe check treats intentional identity calibration as
  "uncalibrated" (`engine/probe_interpreter.py`).

### 6. Other ops/security (LOWER)
- Dependency pinning (`pyproject.toml` `>=`, `package.json` `^`) + lockfile CI check.
- `pytest-cov` coverage gate in CI.
- Frontend Dockerfile `--legacy-peer-deps` (peer-dep conflicts hidden).
- CORS: no test asserts rejected origins; make `CORS_ORIGINS` required in prod.

---

## Already resolved earlier (do NOT redo)
- **Flowmeter deviation table** now uses server-side interior-event deviations
  (`flowmeter-deviations` endpoint), not client-side `total_m3_ha` (commit
  `f911960`). The remaining `total_m3_ha` uses are legitimate total-consumption.
- **Flowmeter 406 (Conqueiros)** — credential issue, re-fixed via
  `set_farm_credentials.py`; not a code bug.

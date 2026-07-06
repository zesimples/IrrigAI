# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

IrrigAI is a precision-irrigation decision-support platform. A **deterministic agronomic engine** computes water-balance recommendations (ET₀, crop demand, drainage thresholds, dosage); an **LLM explanation layer** (OpenAI GPT-4o-mini) converts those recommendations into natural-language explanations — the LLM never makes agronomic decisions. A background **ingestion worker** pulls probe readings and weather data from external providers on a schedule.

---

## Development commands

All commands assume Docker Compose is running. Run them from the repo root.

```bash
make dev              # Start all services with hot-reload
make down             # Stop services
make down-v           # Stop and remove volumes (fresh DB)

make migrate                      # alembic upgrade head (inside container)
make makemigration msg="<text>"   # autogenerate migration from model changes

make test-backend     # pytest -v inside container
make test-frontend    # cd frontend && npm run test:run (Vitest)
make test-e2e         # Playwright E2E (requires running stack)

make lint             # ruff check + ruff format --check
make format           # ruff format (auto-fix)
make seed             # seed DB with test data (dev login: you@irrigai.dev / irrigai-dev)
make shell-backend    # bash inside backend container
make logs-backend     # follow backend logs
```

**Run a single backend test:**
```bash
docker compose exec backend pytest tests/test_engine/test_water_balance.py -v
# or locally:
cd backend && pytest tests/test_engine/test_water_balance.py -x -q --tb=short
```

**Local backend (outside Docker):**
```bash
cd backend && pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://irrigai:irrigai_dev@localhost:5434/irrigai
export DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@localhost:5434/irrigai
export REDIS_URL=redis://localhost:6380/0
export SECRET_KEY=local-dev-secret
export ENCRYPTION_KEY=local-dev-encryption-key
export LLM_PROVIDER=mock PROBE_PROVIDER=mock WEATHER_PROVIDER=mock
```

**Production deploys:**
- Backend-only changes: `git pull && docker compose up -d --build backend` (and `--build worker` if engine/scheduler code changed). The `backend`/`worker` services bake code into the image at build time — there is **no source volume mount** in production — so `docker compose restart` runs the *old* image and silently serves stale code. Always rebuild.
- Frontend changes: `git pull && docker compose up -d --build frontend`
- Schema changes: run `make migrate` after pulling

---

## Architecture

```
PostgreSQL 16 + TimescaleDB   ←  probe readings time-series
Redis 7                        ←  job locks, rate-limit counters
APScheduler (worker container) ←  periodic ingestion + recommendation jobs
FastAPI (backend container)    ←  REST API at /api/v1
Next.js 14 (frontend container)←  App Router UI, proxies /api/v1 → backend
```

### Backend (`backend/app/`)

| Directory | Purpose |
|-----------|---------|
| `engine/` | **Deterministic agronomic engine** — water balance, ET₀, crop demand, dosage, stress projection, trigger logic. Entry point: `engine/pipeline.py` (`RecommendationPipeline`). Also `soil_water_model.py` + `soil_water_data.py`: a rain-anchored FAO-56 running balance that, for **probe-less sectors that have a flowmeter**, replaces the static 70%-of-TAW seed using measured irrigation + weather history (probes stay authoritative elsewhere). Every parameter comes from DB records, never hardcoded. |
| `ai/` | **LLM explanation layer** — `assistant.py` orchestrates context → prompt → LLM; `context_builder.py` fetches all DB context before calling the LLM; `prompt_templates.py` defines structured output schemas; `probe_signal.py` computes signal statistics (flatline, drainage events). |
| `adapters/` | **Provider abstraction** — `factory.py` selects mock/irriwatch/myirrigation at runtime via `PROBE_PROVIDER` / `WEATHER_PROVIDER` env vars. All adapters implement the interface in `base.py`. |
| `api/v1/` | REST endpoints grouped by resource (farms, plots, sectors, probes, recommendations, chat, …). Unified by `router.py`. |
| `models/` | SQLAlchemy 2.0 async ORM models. |
| `schemas/` | Pydantic v2 request/response schemas, including `schemas/ai.py` for structured LLM output. |
| `alerts/engine.py` | Alert generation from recommendation state changes. |
| `anomaly/` | Rule-based anomaly detection on probe readings. |
| `services/scheduler.py` | APScheduler jobs (data + flowmeter ingestion, daily recommendations, alert check, reference recompute). Redis locks (`job_lock.py`) prevent duplicate runs. Per-farm jobs run through `_run_per_farm_job` → `classify_per_farm_run` records `success` / `partial_failure` / `failure` (an all-farms-failed run no longer logs "success") plus the `scheduler_farm_failures_total` metric. Stamps a Redis liveness heartbeat (`app/heartbeat.py`) on startup and after every job. |
| `access.py` | Per-tenant authorization controller — see **API security** below. |

**AI structured output flow:**
1. `IrrigationAssistant` (in `ai/assistant.py`) calls `context_builder` → builds `AgronomicInterpretation` (Pydantic schema in `schemas/ai.py`) via structured OpenAI output.
2. `render_structured(interpretation)` converts the structured output to `• Label: Value` bullet lines for the frontend.
3. Frontend `parseResultBullets()` in `SectorAnalysis.tsx` parses these bullets into the styled card UI.

**Structured-output PT contract (`_complete_structured`):** every card endpoint routes through `assistant._complete_structured`, which appends `prompt_templates.get_structured_output_contract(language)` to the system prompt before calling `client.complete_structured` (native `beta.chat.completions.parse`). The contract forces the model to (a) fill **all** fields in European Portuguese — translating any English context values (e.g. the engine's "No sector crop profile attached") — and (b) set `evidence[].source` to **canonical context paths** (`water_balance`, `recommendation_history`, `weather.forecast`, `probe_signal`, `known_limitations`, …) that `render_structured`'s `_SRC_LABEL` maps to PT labels. This restores guidance that lived in the deleted `STRUCTURED_OUTPUT_PT`: the native-`.parse` migration dropped it, and the schema (`schemas/ai.py`) has no field descriptions, so without the contract the model returned English fields and invented source paths (e.g. `sectors.recommendation_action`) that rendered as raw bullets like "Sectors Recommendation Action: irrigate". CI uses the mock client, which does not exercise real `.parse` language behavior — so regressions here surface only under `LLM_PROVIDER=openai`.

**Probe-pattern interpretation guard:** `probe_signal.py` attaches the sector's `latest_recommendation` (engine action + `depletion_pct`) to the signal stats. After the LLM returns, `assistant._apply_probe_recommendation_guard()` deterministically overrides the advice when the engine reports no deficit (`action` ∈ {`skip`, `defer`} or `depletion_pct ≤ 5%`) — it forces `risk_level=low`, monitoring-only actions, and injects the engine evidence. This enforces the rule that the LLM never overrides the deterministic engine: an isolated "humidade crítica" depth is treated as a possible sensor discrepancy, not a reason to irrigate. Note: the engine reports "don't irrigate" via `RecommendationAction.skip` / `.defer` (see `core/enums.py`) — there is no `no_irrigation` value.

**Soil-water source (`swc_source`):** the pipeline records how rootzone SWC was obtained on each recommendation — `probe_weighted` (probe, authoritative), `water_balance_model` (the FAO-56 model for probe-less + flowmeter sectors), or `default_estimate` (static 70%-of-TAW seed). Surfaced in `Recommendation.inputs_snapshot` (`swc_source` + `swc_model` metadata). The model never runs when a probe is present, and degrades to the static seed on any error (per-sector try/except).

**Probe soil calibration ("Calibração AI"):** `engine/auto_calibration.py` derives a sector's CC (`observed_fc`) and effective refill line (`observed_refill`) **deterministically** from the probe's own VWC envelope (cycle-based, else percentile envelope) — *no LLM decides soil numbers* (the button label is user-facing only). `ProbeCalibrationService.compute_and_save` upserts one `probe_calibration` row per sector. `pipeline.resolve_sector_soil_bounds` is the single resolver shared by the engine and the probe chart (`api/v1/probes`), so CC/PMP reference lines can't diverge from the FC the engine uses. Precedence (`engine/soil_bounds.resolve_soil_bounds`, pure/unit-tested): `scp_override` (customized) > `probe_calibrated` > `scp` > `plot_preset` > `default`.
- **Recency rule (last action wins), enforced at the API layer, not the resolver:** `POST /sectors/{id}/auto-calibration/run` clears the sector's `SectorCropProfile.is_customized` so a fresh calibration takes precedence; a later manual soil/CC-PMP edit (`PUT /sectors/{id}/crop-profile`) re-sets `is_customized=True` and overrides the calibration again. The pure resolver always treats `is_customized` as authoritative — the clearing/setting lives in those two endpoints.
- **Staleness:** `CALIB_MAX_AGE_DAYS=90`; `is_calibration_stale(computed_at)` makes the resolver ignore an old calibration (falls through to the next source) while still surfacing its metadata as `used=False/stale=True`. Solved in code via `computed_at` — no schema column.
- **`/run` response + UI feedback:** returns `observed_*`, effective `previous_*`/`effective_*` bounds, `changed`, `applied`, `cleared_customization`. The `AiCalibrationButton` toast reports the real CC transition ("CC 17→24") and always refreshes the probe chart (`ProbeReadingsInline` `refreshTrigger`); the recommendation regenerates only when the effective bounds moved.
- **Tension/Watermark sectors can't calibrate** (the model needs `vwc_m3m3`, not `soil_tension_cbar`): `/run` returns a specific 422 (`diagnose_unavailable`), and the sector-status `calibration_available` flag disables the button (tooltip) for them. At Herdade do Esporão only the Olival (olive) sectors are Watermark; everything else is VWC.
- **Calibration is manual-trigger only** (the weekly scheduler also recomputes — `_run_recompute_probe_calibration`); there is no daily auto-calibration.

**Dose do dia (dose-centric recommendation):** the headline is a 4-band dose (`reforcada`/`normal`/`curta`/`pode_saltar` — `engine/dose_presentation.py`), not a binary verdict; dosage is computed on **every** pipeline run (reserve days get a reduced dose). Dose source precedence (mirrors `swc_source`, stored in `inputs_snapshot`): `configured` (application rate/emitters) > `probe_learned` (per-sector `irrigation_fingerprint` learned weekly from probe-detected irrigation events, 25-day window/staleness, ≥3 usable events, VWC-only) > `mm_only`. `RecommendationAction` (irrigate/skip/defer) is unchanged underneath — alerts and AI guards still key off it.

**Probe `external_id` ↔ MyIrrigation device:** `external_id` is `"{project_id}/{device_id}"` (e.g. `1597/9287`). When a device is **renamed in the MyIrrigation portal its `device_id` changes**, so our stored `external_id` 404s and that sector silently stops ingesting (the in-app sector rename is harmless — it only changes `Sector.name`). Fix is a DB update of `Probe.external_id` (keep the project prefix, swap the device id); `last_reading_at` left as-is auto-backfills the gap (adaptive lookback caps at 168h). There is no UI to edit `external_id` yet.

**Per-farm MyIrrigation credentials:** stored **encrypted** in the `farm_credentials` table (`EncryptedString`), overriding the global `MYIRRIGATION_*` env vars per farm. There is no API/UI to edit them — use `scripts/set_farm_credentials.py` (env-driven, prints no secrets, `VERIFY=1` replays a real device-data call). The 406 "Client Signature Invalid" outage was a wrong stored credential, not a code bug. The Fernet key comes from `ENCRYPTION_KEY` (see below) — **changing it makes existing ciphertext undecryptable** (`decrypt()` returns `None`, not an error), so keep it stable or re-run `set_farm_credentials.py` after a rotation. `farm_credentials` also holds a plaintext `weather_device_id` and (since the Innoliva onboarding) a plaintext `project_id`; `adapters/factory._get_myirrigation` threads both into the adapter, so each farm resolves its own MyIrrigation project's weather. Farms whose creds omit `project_id` fall back to the global `MYIRRIGATION_PROJECT_ID` (unchanged behaviour for Esporão/Conqueiros).

**One farm, plots spanning several MyIrrigation projects + per-plot weather (ADL / Innoliva pattern):** a farm's probes may belong to *different* MyIrrigation projects — the `external_id` (`{project_id}/{device_id}`) carries each probe's project, and probe reads are project-agnostic (they only use `device_id`). **ADL** ("Herdade das Amendoas do Lago") is one farm whose plots Castelos Norte / Falcão / Valemoura sit on projects 964 / 963 / 1162 and share one farm-level weather station. **Innoliva** is one farm, 6 plots (the "polos": Conceição/Covadonga/Fátima/Guadalupe/Rocio/Carmo, rendered as the farm-page plot tabs), 77 olive sectors — but with **per-plot weather**: each `Plot` carries its own `myirrigation_project_id` + iMetos `weather_device_id`, so each polo's sectors use that polo's own iMetos for ET₀ (Conceição has no iMetos → forecast-only). Weather resolution:
- **Weather tables** (`weather_observation`, `weather_forecast`) carry a nullable `plot_id`. `plot_id IS NULL` = farm-level weather (all pre-existing farms: Esporão/Conqueiros/ADL — behaviour unchanged).
- **Ingestion** (`services/ingestion.py` `ingest_farm`): if any of the farm's plots has weather config, fetch weather per-plot (each with its `project_id`/`weather_device_id`, stored with `plot_id`); otherwise the single farm-level fetch (`plot_id=NULL`). A device-less plot (Conceição) fetches forecast only — the observation fetch is skipped so it doesn't fall back to the adapter's global instance device. **Weather ingestion is gated on `farm.location_lat/lon` being set** — a per-plot-weather farm must still have a farm location (Innoliva onboarding sets a representative one).
- **Engine** (`engine/pipeline.py` `build_weather_context(farm_id, db, plot_id=None)`): resolves a sector's weather by its plot; falls back to farm-level (`plot_id IS NULL`); and for a farm-level caller on a farm that has **only** plot-scoped rows (Innoliva), falls back to a representative plot (the farm's most-recent-observation plot) so farm-summary / rain-skip callers still get data.
- **Adapter** weather methods take an optional per-call `project_id`/`weather_device_id` (override instance state) so one shared adapter/token serves all plots.

**Token contention caveat (Innoliva's polos share one `client_id`):** MyIrrigation invalidates a prior JWT when the same `client_id` logs in again; the adapter's `_is_client_signature_invalid` → re-auth path (fix `e107777`) self-heals each poisoned call ("ship-simple + monitor"; a shared-token-per-account refactor is the contingency if churn appears). Onboarding is a one-off idempotent script (`backend/scripts/onboard_innoliva.py`; device discovery `backend/scripts/innoliva_discover.py` → `docs/innoliva_device_mapping.csv`), not a UI.

**API security (authentication + ownership):** every `/api/v1` endpoint requires a valid bearer token — `router.py` attaches `Depends(get_current_user)` to every router group **except `auth`** (token issue/register). New routers added there inherit auth automatically; don't rely on per-endpoint `current_user` params for the gate. Authorization is per-tenant via `app/access.py` `AccessController` (dependency `Access`), which resolves farm/plot/sector/probe/recommendation/irrigation_event/alert/override/water_event scoped to the caller's owned farm chain (`farm.owner_id`); **`role == "admin"` bypasses ownership** and sees all farms. Missing *and* cross-tenant resources both return **404** (no existence leak). Global catalogs (`crop-profile-templates`, `soil-presets`) stay readable by any authed user; `/audit-log` is **admin-only**. Operator/staff accounts (e.g. `you@irrigai.dev`) should be `admin`; client accounts own their own farm. Note: agronomist is *not* admin-bypassed — an agronomist owning no farms currently sees nothing.

**Startup security guard:** `config.check_production_security()` runs in the backend lifespan and `worker.main()` and **aborts boot** when `DEBUG=false` and `ENCRYPTION_KEY` is unset (would derive the encryption key from `SECRET_KEY`) or `SECRET_KEY` is still the `change-me-in-production` placeholder. A crash-looping backend behind nginx surfaces as 500s on every API call.

### Frontend (`frontend/src/`)

| Directory | Purpose |
|-----------|---------|
| `app/` | Next.js App Router pages. Key routes: `/farms/[farmId]`, `/farms/[farmId]/sectors/[sectorId]`, `/farms/[farmId]/sectors/[sectorId]/probes/[probeId]` |
| `components/sectors/` | `SectorAnalysis.tsx` — main AI analysis card with `parseResultBullets` / `AssistantResult`. `SectorDiagnosisCard.tsx` — diagnosis panel. `AiCalibrationButton.tsx` — manual "Calibração AI" trigger (recency/override toast; disabled on tension sectors). |
| `components/probes/` | `ProbeReadingsInline.tsx` — chart + water event management (confirm/reject/reclassify). `ReadingsControls.tsx` — view/interval selector (Bruto disabled for Soma view). |
| `lib/api.ts` | All API calls. Centralized typed wrappers for every backend endpoint. |
| `types/index.ts` | All TypeScript types shared across the app. |

**Chart view modes** in `ProbeReadingsInline.tsx`:
- `"depth"` — per-depth VWC series (deduped server-side by `depth_cm`)
- `"sum"` — summed VWC across all depths (Bruto resolution disabled; auto-clamps to 1h on switch)

### Database

- **TimescaleDB** hypertable on `probe_reading` for time-series queries.
- `ProbeDepth` records: multiple rows can share the same `depth_cm` (provider duplicates). The `/probes/{id}/readings` endpoint groups by `depth_cm` and deduplicates timestamps before returning series. **Ingestion does NOT auto-create `ProbeDepth` rows** — `ingestion._store_readings` *skips* any reading whose `depth_cm` has no matching `ProbeDepth` ("No ProbeDepth record for depth=…cm — skipping"). So a probe with no `ProbeDepth` rows silently ingests nothing; onboarding must pre-create them (e.g. `onboard_innoliva.py` discovers each device's actual sensor depths from the API — depths vary per device, e.g. 5/15/…/55 vs 10/20/…/60 cm). `sensor_type` for VWC probes is `"soil_moisture"` (matches `seed.py` + the `compute_and_save` calibration path; note the pre-existing outlier `auto_calibration.analyze_sector`, which matches `"moisture"` exactly and so returns null for VWC sectors on the calibration *preview* endpoint — the `/run` path works).
- Alembic migrations live in `backend/alembic/versions/`. Always run `make migrate` after pulling on production.

### Environment variables (key ones)

| Variable | Values |
|----------|--------|
| `PROBE_PROVIDER` | `mock` / `irriwatch` / `myirrigation` |
| `WEATHER_PROVIDER` | `mock` / `openweathermap` |
| `LLM_PROVIDER` | `mock` / `openai` |
| `DEFAULT_LANGUAGE` | `pt` (default, Portuguese) |
| `DEBUG` | `false` in prod — arms the startup security guard |
| `SECRET_KEY` | JWT signing; must be a strong unique value in prod (not the placeholder) |
| `ENCRYPTION_KEY` | Fernet key for `farm_credentials`; **mandatory when `DEBUG=false`** (falls back to `SECRET_KEY` only in dev). Keep stable — see per-farm credentials above |

CI always uses `mock` for all three providers.

**Container health:** `docker-compose.yml` healthchecks the backend (`/health`) and the worker (`python -m app.worker_health`, which reads the scheduler heartbeat — the worker has no HTTP server). In prod, nginx waits for the backend to be `service_healthy`.

---

## Testing

- Backend tests use `pytest-asyncio` (`asyncio_mode = "auto"`). All async test functions run automatically.
- Tests under `tests/test_api/` run against test Postgres (NullPool per request) — see `conftest.py`.
- **Auth in tests:** since global auth landed, data-focused fixtures override `get_current_user`. `test_api/conftest.py` exposes `client` (authenticated as the seeded owner `you@irrigai.dev`, get-or-created) and `noauth_client` (real token flow, used by `test_auth_permissions.py`). CI runs `python -m app.seed` before pytest, which creates that owner. The e2e fixture flags the seeded user `admin` in-memory for the global audit-log assertion.
- Frontend unit tests: Vitest (`npm run test:run`).
- E2E: Playwright (`npm run e2e`), requires the full stack running.
- CI (`.github/workflows/ci.yml`) runs the backend suite and `frontend-lint`; it does **not** run backend `ruff` (pre-existing project-wide `B008` on FastAPI `Depends()` defaults is not gated).

---

## Code style

- **Python**: ruff, line-length 100, target py312. Rules: E, F, I (isort), UP (pyupgrade), B (bugbear), SIM.
- **TypeScript**: ESLint (`.eslintrc.json`), strict TypeScript.
- Migrations are always **autogenerated** (`make makemigration`), never hand-written — verify the diff before committing.

---

## Roadmap / next topics

Detailed tracking in `docs/handoff-codex-2026-06-17.md`.

**Done in the 2026-06-17 security/ops cycle:** farm-summary prompt `no_irrigation` fix; API authentication on all v1 endpoints; per-tenant ownership (`access.py`); mandatory-prod `ENCRYPTION_KEY` startup guard; backend + worker healthchecks; scheduler partial-failure observability + heartbeat.

**Done in the 2026-06-26 calibration cycle:** manual "Calibração AI" trigger (`POST /sectors/{id}/auto-calibration/run`) with recency precedence (button clears `is_customized`; manual edit re-overrides); 90-day staleness guardrail; honest 422 / override / no-change feedback + probe-chart auto-refresh; button disabled on tension/Watermark sectors via sector-status `calibration_available`; recommendation reason-text localization (`pipeline.py` + `ReasonList.tsx`); API test fixtures self-clean their farm subtree. See **Probe soil calibration** above.

**Done in the 2026-07-01 cycle:** restored the structured-output PT contract in `_complete_structured` (fixes English/raw-bullet regression from the native-`.parse` migration — see **AI structured output flow**); `project_id` on `FarmCredentials` + factory wiring (merged).

**Done in the 2026-07-03 cycle (merged `0ce78e1`, DEPLOYED to prod — Innoliva is live):** Innoliva onboarding **remodelled** to ONE farm + a plot per polo (superseding the earlier 6-farm design), 77 VWC-probe olive sectors; and **per-plot weather** (Plot weather config, `plot_id` on weather tables, per-call adapter project/device, per-plot ingestion, `build_weather_context` plot resolution with farm + representative-plot fallback) — see **One farm, plots spanning several MyIrrigation projects** above. Onboarding also sets a representative farm location and skips observation fetch for device-less plots (Conceição forecast-only). Client login `innoliva@irrigai.pt` (role `grower`) owns only the Innoliva farm → sees only Innoliva.

**Done in the 2026-07-06 cycle:** Dose do dia — dose-centric recommendation headline (4 bands + configured/probe_learned/mm_only source precedence, per-sector irrigation fingerprint learned from probe-detected events, weekly scheduler job). See **Dose do dia** above.

**Deploy/ops gotchas learned in the 2026-07-03 prod rollout (all real, keep in mind):**
- **`onboard_innoliva.py` is get-or-create by email for the owner User and does NOT update an existing user's password on re-run.** If the account was created on an earlier run, its password is whatever that run set — reset it with `app.auth.hash_password` (login checks `verify_password` **and** `user.is_active`). It also does not ingest readings — it only builds structure + `ProbeDepth` rows (from live sensor discovery); readings come from the ingestion job (scheduler, or a manual `ingest_farm(farm_id, db, lookback_hours=…)`).
- **The `plot_id` FK on `weather_observation`/`weather_forecast` has NO `ON DELETE` rule and no ORM cascade** → deleting a Plot (or a farm's plots) is blocked by weather rows referencing them. To delete Innoliva-style data, delete the farm's `WeatherForecast`/`WeatherObservation` rows FIRST, then the farm (which cascades plots→sectors→probes→depths→readings). (Follow-up: add `ON DELETE SET NULL` to those FKs.)
- **Bulk deletes of farm subtrees deadlock with the running worker** (the scheduler ingests/recommends the same rows concurrently). `docker compose stop worker` before large deletes, then `start worker` after.
- **Migration index drops must be `DROP INDEX IF EXISTS`** — the model-declared composite indexes (`ix_weather_obs_farm_timestamp`, `ix_weather_forecast_farm_date`) existed on dev but NOT prod (dev/prod index drift), so a plain `op.drop_index` failed on prod (fixed in `6e5069f0c5fd`).
- Re-running onboarding after a partial/duplicate state: the old probes' `external_id`s block the new run from creating probes (get-or-create finds them), leaving new sectors probe-less — do a full wipe of the owner's farms (weather-first) then a single clean re-run.

**Open, roughly prioritized:**
0. **Per-plot-weather follow-ups** (Innoliva is deployed & live): add `ON DELETE SET NULL` to the weather `plot_id` FKs (so plot deletion isn't blocked); add an integration test for the `ingest_farm` per-plot vs farm-level branch dispatch; fix the pre-existing `auto_calibration.analyze_sector` `"moisture"`-vs-`"soil_moisture"` mismatch (calibration preview returns null for VWC sectors; `/run` works).
1. **Rate limiting** on `/auth/*` (token, register) and `/chat/*` — only the recommendation endpoints are limited today (`app/limiter.py`); credential-stuffing and LLM-cost exposure. *(Next up.)*
2. **E2E Playwright job** — stabilize stack-boot and make it a required check, or stop treating it as a gate (currently red/never-green on main; backend suite is green).
3. **Frontend data-fetching & coverage** — `useEffect` fetch waterfalls + races on rapid param change (`ProbeReadingsInline.tsx`); all-or-nothing `Promise.all` (`FlowmeterDashboard.tsx`). Adopt React Query/SWR or at least `Promise.allSettled` + `AbortController`. Thin Vitest coverage on core components; large `sectors/[sectorId]/page.tsx`.
4. **Engine-correctness review (UNVERIFIED — confirm before acting):** zero-TAW division (`engine/trigger.py`), probe-unit validation accepting VWC when `unit != vwc_m3m3` (`engine/probe_interpreter.py`), ingestion dedup idempotency on partial/crashed runs (`services/ingestion.py`).
5. **Agronomist-role access** — `AccessController` only bypasses for `admin`; agronomist accounts owning no farms see nothing. Decide whether agronomists need read access (make admin, grant ownership, or extend the controller).
6. **Edit probe `external_id` from the UI** — a MyIrrigation device rename changes its `device_id`, silently stopping that sector's ingestion; the only fix today is a manual DB update. A small admin field (with a `VERIFY`-style provider check) would avoid the DB round-trip each time. See **Probe `external_id` ↔ MyIrrigation device** above.
7. **Lower:** dependency pinning + lockfile CI check; `pytest-cov` coverage gate; frontend Dockerfile `--legacy-peer-deps`; CORS reject-origin test.

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

**Probe-pattern interpretation guard:** `probe_signal.py` attaches the sector's `latest_recommendation` (engine action + `depletion_pct`) to the signal stats. After the LLM returns, `assistant._apply_probe_recommendation_guard()` deterministically overrides the advice when the engine reports no deficit (`action` ∈ {`skip`, `defer`} or `depletion_pct ≤ 5%`) — it forces `risk_level=low`, monitoring-only actions, and injects the engine evidence. This enforces the rule that the LLM never overrides the deterministic engine: an isolated "humidade crítica" depth is treated as a possible sensor discrepancy, not a reason to irrigate. Note: the engine reports "don't irrigate" via `RecommendationAction.skip` / `.defer` (see `core/enums.py`) — there is no `no_irrigation` value.

**Soil-water source (`swc_source`):** the pipeline records how rootzone SWC was obtained on each recommendation — `probe_weighted` (probe, authoritative), `water_balance_model` (the FAO-56 model for probe-less + flowmeter sectors), or `default_estimate` (static 70%-of-TAW seed). Surfaced in `Recommendation.inputs_snapshot` (`swc_source` + `swc_model` metadata). The model never runs when a probe is present, and degrades to the static seed on any error (per-sector try/except).

**Per-farm MyIrrigation credentials:** stored **encrypted** in the `farm_credentials` table (`EncryptedString`), overriding the global `MYIRRIGATION_*` env vars per farm. There is no API/UI to edit them — use `scripts/set_farm_credentials.py` (env-driven, prints no secrets, `VERIFY=1` replays a real device-data call). The 406 "Client Signature Invalid" outage was a wrong stored credential, not a code bug. The Fernet key comes from `ENCRYPTION_KEY` (see below) — **changing it makes existing ciphertext undecryptable** (`decrypt()` returns `None`, not an error), so keep it stable or re-run `set_farm_credentials.py` after a rotation.

**API security (authentication + ownership):** every `/api/v1` endpoint requires a valid bearer token — `router.py` attaches `Depends(get_current_user)` to every router group **except `auth`** (token issue/register). New routers added there inherit auth automatically; don't rely on per-endpoint `current_user` params for the gate. Authorization is per-tenant via `app/access.py` `AccessController` (dependency `Access`), which resolves farm/plot/sector/probe/recommendation/irrigation_event/alert/override/water_event scoped to the caller's owned farm chain (`farm.owner_id`); **`role == "admin"` bypasses ownership** and sees all farms. Missing *and* cross-tenant resources both return **404** (no existence leak). Global catalogs (`crop-profile-templates`, `soil-presets`) stay readable by any authed user; `/audit-log` is **admin-only**. Operator/staff accounts (e.g. `you@irrigai.dev`) should be `admin`; client accounts own their own farm. Note: agronomist is *not* admin-bypassed — an agronomist owning no farms currently sees nothing.

**Startup security guard:** `config.check_production_security()` runs in the backend lifespan and `worker.main()` and **aborts boot** when `DEBUG=false` and `ENCRYPTION_KEY` is unset (would derive the encryption key from `SECRET_KEY`) or `SECRET_KEY` is still the `change-me-in-production` placeholder. A crash-looping backend behind nginx surfaces as 500s on every API call.

### Frontend (`frontend/src/`)

| Directory | Purpose |
|-----------|---------|
| `app/` | Next.js App Router pages. Key routes: `/farms/[farmId]`, `/farms/[farmId]/sectors/[sectorId]`, `/farms/[farmId]/sectors/[sectorId]/probes/[probeId]` |
| `components/sectors/` | `SectorAnalysis.tsx` — main AI analysis card with `parseResultBullets` / `AssistantResult`. `SectorDiagnosisCard.tsx` — diagnosis panel. |
| `components/probes/` | `ProbeReadingsInline.tsx` — chart + water event management (confirm/reject/reclassify). `ReadingsControls.tsx` — view/interval selector (Bruto disabled for Soma view). |
| `lib/api.ts` | All API calls. Centralized typed wrappers for every backend endpoint. |
| `types/index.ts` | All TypeScript types shared across the app. |

**Chart view modes** in `ProbeReadingsInline.tsx`:
- `"depth"` — per-depth VWC series (deduped server-side by `depth_cm`)
- `"sum"` — summed VWC across all depths (Bruto resolution disabled; auto-clamps to 1h on switch)

### Database

- **TimescaleDB** hypertable on `probe_reading` for time-series queries.
- `ProbeDepth` records: multiple rows can share the same `depth_cm` (provider duplicates). The `/probes/{id}/readings` endpoint groups by `depth_cm` and deduplicates timestamps before returning series.
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

**Open, roughly prioritized:**
1. **Rate limiting** on `/auth/*` (token, register) and `/chat/*` — only the recommendation endpoints are limited today (`app/limiter.py`); credential-stuffing and LLM-cost exposure. *(Next up.)*
2. **E2E Playwright job** — stabilize stack-boot and make it a required check, or stop treating it as a gate (currently red/never-green on main; backend suite is green).
3. **Frontend data-fetching & coverage** — `useEffect` fetch waterfalls + races on rapid param change (`ProbeReadingsInline.tsx`); all-or-nothing `Promise.all` (`FlowmeterDashboard.tsx`). Adopt React Query/SWR or at least `Promise.allSettled` + `AbortController`. Thin Vitest coverage on core components; large `sectors/[sectorId]/page.tsx`.
4. **Engine-correctness review (UNVERIFIED — confirm before acting):** zero-TAW division (`engine/trigger.py`), probe-unit validation accepting VWC when `unit != vwc_m3m3` (`engine/probe_interpreter.py`), ingestion dedup idempotency on partial/crashed runs (`services/ingestion.py`).
5. **Agronomist-role access** — `AccessController` only bypasses for `admin`; agronomist accounts owning no farms see nothing. Decide whether agronomists need read access (make admin, grant ownership, or extend the controller).
6. **Lower:** dependency pinning + lockfile CI check; `pytest-cov` coverage gate; frontend Dockerfile `--legacy-peer-deps`; CORS reject-origin test.

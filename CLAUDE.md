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
make seed             # seed DB with test data
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
- Backend-only changes: `git pull && docker compose restart backend`
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
| `engine/` | **Deterministic agronomic engine** — water balance, ET₀, crop demand, dosage, stress projection, trigger logic. Entry point: `engine/pipeline.py` (`RecommendationPipeline`). Every parameter comes from DB records, never hardcoded. |
| `ai/` | **LLM explanation layer** — `assistant.py` orchestrates context → prompt → LLM; `context_builder.py` fetches all DB context before calling the LLM; `prompt_templates.py` defines structured output schemas; `probe_signal.py` computes signal statistics (flatline, drainage events). |
| `adapters/` | **Provider abstraction** — `factory.py` selects mock/irriwatch/myirrigation at runtime via `PROBE_PROVIDER` / `WEATHER_PROVIDER` env vars. All adapters implement the interface in `base.py`. |
| `api/v1/` | REST endpoints grouped by resource (farms, plots, sectors, probes, recommendations, chat, …). Unified by `router.py`. |
| `models/` | SQLAlchemy 2.0 async ORM models. |
| `schemas/` | Pydantic v2 request/response schemas, including `schemas/ai.py` for structured LLM output. |
| `alerts/engine.py` | Alert generation from recommendation state changes. |
| `anomaly/` | Rule-based anomaly detection on probe readings. |
| `services/scheduler.py` | APScheduler job definitions (ingestion, recommendation generation). Uses Redis locks (`job_lock.py`) to prevent duplicate runs. |

**AI structured output flow:**
1. `IrrigationAssistant` (in `ai/assistant.py`) calls `context_builder` → builds `AgronomicInterpretation` (Pydantic schema in `schemas/ai.py`) via structured OpenAI output.
2. `render_structured(interpretation)` converts the structured output to `• Label: Value` bullet lines for the frontend.
3. Frontend `parseResultBullets()` in `SectorAnalysis.tsx` parses these bullets into the styled card UI.

**Probe-pattern interpretation guard:** `probe_signal.py` attaches the sector's `latest_recommendation` (engine action + `depletion_pct`) to the signal stats. After the LLM returns, `assistant._apply_probe_recommendation_guard()` deterministically overrides the advice when the engine reports no deficit (`action = no_irrigation` or `depletion_pct ≤ 5%`) — it forces `risk_level=low`, monitoring-only actions, and injects the engine evidence. This enforces the rule that the LLM never overrides the deterministic engine: an isolated "humidade crítica" depth is treated as a possible sensor discrepancy, not a reason to irrigate. Note: the engine reports "don't irrigate" via `RecommendationAction.skip` / `.defer` (see `core/enums.py`) — there is no `no_irrigation` value.

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

CI always uses `mock` for all three providers.

---

## Testing

- Backend tests use `pytest-asyncio` (`asyncio_mode = "auto"`). All async test functions run automatically.
- Tests under `tests/test_api/` use an in-memory async SQLite or test Postgres — see `conftest.py`.
- Frontend unit tests: Vitest (`npm run test:run`).
- E2E: Playwright (`npm run e2e`), requires the full stack running.

---

## Code style

- **Python**: ruff, line-length 100, target py312. Rules: E, F, I (isort), UP (pyupgrade), B (bugbear), SIM.
- **TypeScript**: ESLint (`.eslintrc.json`), strict TypeScript.
- Migrations are always **autogenerated** (`make makemigration`), never hand-written — verify the diff before committing.

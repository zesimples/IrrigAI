# IrrigAI

AI-powered irrigation planning and recommendation system for agriculture.

Combines a **deterministic agronomic engine** (water balance, ETc, depletion thresholds) with an **OpenAI explanation layer** — the LLM explains recommendations, never makes them.

## Stack

- **Frontend:** Next.js 14+ (App Router) + TypeScript + Tailwind CSS + shadcn/ui
- **Backend:** Python FastAPI + SQLAlchemy 2.0 (async) + Alembic
- **Database:** PostgreSQL 16 + TimescaleDB
- **Cache:** Redis 7
- **AI:** OpenAI GPT-4o-mini (explanation only)
- **Background jobs:** APScheduler

## Quick Start

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY or leave LLM_PROVIDER=mock for local dev

make dev
```

Services:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Development Commands

```bash
make dev              # Start all services with hot-reload
make down             # Stop services
make migrate          # Run Alembic migrations
make makemigration msg="add sector table"
make seed             # Seed DB with crop templates and test data
make test-backend     # Run pytest
make lint             # Ruff lint + format check
```

## Architecture

```
User Forms → PostgreSQL ← External APIs (probes, weather)
                 ↓
       Agronomic Engine (deterministic)
                 ↓
       OpenAI ChatGPT (explanation only)
                 ↓
              Frontend
```

See `docs/adr/001-hybrid-architecture.md` for the decision record.

## Data Providers

IrrigAI uses a provider abstraction — swap vendors by changing `.env` without touching application code.

| `PROBE_PROVIDER` / `WEATHER_PROVIDER` | Description |
|---|---|
| `mock` | Synthetic data for local dev (default) |
| `irriwatch` | IrriWatch / Hydrosat satellite data |
| `myirrigation` | MyIrrigation REST API |

### MyIrrigation Setup

**Required environment variables** (copy `.env.example` → `.env`):

```env
PROBE_PROVIDER=myirrigation
WEATHER_PROVIDER=myirrigation

MYIRRIGATION_BASE_URL=http://api.myirrigation.eu/api/v1
MYIRRIGATION_USERNAME=your_username
MYIRRIGATION_PASSWORD=your_password
MYIRRIGATION_CLIENT_ID=your_client_id
MYIRRIGATION_CLIENT_SECRET=your_client_secret
```

**Discover available projects and devices:**

```bash
docker compose exec backend python -m app.tools.myirrigation_discover
```

This prints each device's `external_id` in `"{project_id}/{device_id}"` format. Use that string when creating a Probe record in IrrigAI.

**Example usage in Python:**

```python
from app.adapters.myirrigation import MyIrrigationAdapter

adapter = MyIrrigationAdapter(
    base_url="http://api.myirrigation.eu/api/v1",
    username="...",
    password="...",
    client_id="...",
    client_secret="...",
)

await adapter.authenticate()
projects = await adapter.get_projects()   # list of project dicts
devices  = await adapter.get_devices()    # list of device dicts
```

**Authentication:** `POST /login` with credentials → JWT cached in-process, auto-refreshed 5 minutes before expiry. A 401/403 response automatically triggers one re-authentication and retry.

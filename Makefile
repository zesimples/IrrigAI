.PHONY: dev down test-backend test-backend-local test-frontend test-e2e migrate makemigration seed lint format shell-backend build

# ── Docker (default) ──────────────────────────────────────────────────────────

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose down

down-v:
	docker compose down -v

build:
	docker compose build

test-backend:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend pytest -v

migrate:
	docker compose exec backend alembic upgrade head

makemigration:
	docker compose exec backend alembic revision --autogenerate -m "$(msg)"

seed:
	docker compose exec backend python -m app.seed

lint:
	docker compose exec backend ruff check .
	docker compose exec backend ruff format --check .

format:
	docker compose exec backend ruff format .

shell-backend:
	docker compose exec backend bash

logs-backend:
	docker compose logs -f backend

logs-db:
	docker compose logs -f db

# ── Local (outside Docker) ─────────────────────────────────────────────────────
# Prerequisites: postgres + redis running locally (or via `make dev` then stop backend/worker).
#
# First-time setup:
#   cd backend && pip install -e ".[dev]"
#   export DATABASE_URL=postgresql+asyncpg://irrigai:irrigai_dev@localhost:5434/irrigai
#   export DATABASE_URL_SYNC=postgresql://irrigai:irrigai_dev@localhost:5434/irrigai
#   export REDIS_URL=redis://localhost:6380/0
#   export SECRET_KEY=local-dev-secret
#   export ENCRYPTION_KEY=local-dev-encryption-key
#   export LLM_PROVIDER=mock PROBE_PROVIDER=mock WEATHER_PROVIDER=mock
#
# Then:
#   make test-backend-local   # runs pytest without Docker

test-backend-local:
	cd backend && pytest -x -q --tb=short

test-frontend:
	cd frontend && npm run test:run

test-e2e:
	cd frontend && npm run e2e

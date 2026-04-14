.PHONY: dev down test-backend migrate makemigration seed lint shell-backend build

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

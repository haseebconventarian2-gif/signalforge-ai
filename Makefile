.PHONY: install install-frontend format lint typecheck test build-frontend check migrate run run-frontend docker-up docker-down

install:
	python -m pip install -e "./backend[dev]"

install-frontend:
	cd frontend && npm install

format:
	cd backend && ruff format app tests

lint:
	cd backend && ruff check app tests alembic
	cd frontend && npm run lint

typecheck:
	cd backend && mypy app

test:
	cd backend && pytest

build-frontend:
	cd frontend && npm run build

check: lint typecheck test build-frontend

migrate:
	cd backend && alembic upgrade head

run:
	cd backend && uvicorn app.main:app --reload

run-frontend:
	cd frontend && npm run dev

docker-up:
	docker compose up --build

docker-down:
	docker compose down

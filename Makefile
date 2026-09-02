SHELL := /bin/sh

-include .env

POSTGRES_DB ?= dishpute
POSTGRES_USER ?= dishpute
POSTGRES_PASSWORD ?= dishpute-local-only
POSTGRES_PORT ?= 5432
DATABASE_URL ?= postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@127.0.0.1:$(POSTGRES_PORT)/$(POSTGRES_DB)
TEST_DATABASE_URL ?= postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@127.0.0.1:$(POSTGRES_PORT)/dishpute_python_test

.PHONY: api-dev db-up db-down db-migrate db-test

api-dev:
	DATABASE_URL="$(DATABASE_URL)" uv run uvicorn dishpute.api:app --reload --host 127.0.0.1 --port 8000

db-up:
	docker compose up -d database

db-down:
	docker compose down

db-migrate:
	DATABASE_URL="$(DATABASE_URL)" uv run alembic upgrade head

db-test:
	docker compose exec -T database createdb -U "$(POSTGRES_USER)" dishpute_python_test 2>/dev/null || true
	DATABASE_URL="$(TEST_DATABASE_URL)" uv run alembic upgrade head
	TEST_DATABASE_URL="$(TEST_DATABASE_URL)" uv run pytest

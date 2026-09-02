SHELL := /bin/sh

POSTGRES_DB ?= dishpute
POSTGRES_USER ?= dishpute

.PHONY: db-up db-down db-migrate db-test

db-up:
	docker compose up -d database

db-down:
	docker compose down

db-migrate:
	docker compose exec -T database psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" -v ON_ERROR_STOP=1 < database/migrations/001_initial_schema.sql

db-test:
	docker compose exec -T database psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" -v ON_ERROR_STOP=1 < database/tests/001_initial_schema_test.sql

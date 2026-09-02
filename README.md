# Dishpute

Dishpute is a shared household planning and workload application. It tracks future work, reserved time, completed work, and each member's contribution without treating the household as a management hierarchy.

The project is currently being developed from the database upward. See [the architecture document](docs/architecture.md) for product and system decisions.

## Current scope

- Python SQLAlchemy models
- Alembic database migrations
- PostgreSQL development environment
- Python model and database-integrity tests

The first Application API supports creating and scheduling Tasks, recording completed work, creating Subtasks, and reading contribution duration. Remote MCP Gateway and Web App implementation will follow.

## Local database

1. Copy `.env.example` to `.env` and choose a local development password.
2. Install the Python environment with `uv sync`.
3. Start PostgreSQL with `make db-up`.
4. Apply migrations with `make db-migrate`.
5. Run Python and database verification with `make db-test`.

The database port is exposed only on the loopback interface for local development.

The readable database definition is [the SQLAlchemy model file](src/dishpute/models.py). Alembic uses those models to generate and apply database migrations.

## Application API

Start the local API with `make api-dev`, then open `http://127.0.0.1:8000/docs` for the interactive API contract.

The initial routes are:

- `POST /households/{household_id}/tasks`
- `POST /households/{household_id}/completed-work`
- `GET /households/{household_id}/contributions`

During this first development stage, the authenticated caller is represented by the `X-Actor-User-Id` header. OAuth will replace this temporary mechanism before the API is publicly exposed.

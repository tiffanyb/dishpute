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
- `GET /households/{household_id}/tasks`
- `GET /households/{household_id}/tasks/{task_id}`
- `PATCH /households/{household_id}/tasks/{task_id}`
- `POST /households/{household_id}/tasks/{task_id}/time-blocks`
- `PATCH /households/{household_id}/time-blocks/{time_block_id}`
- `PATCH /households/{household_id}/tasks/{task_id}/lifecycle`
- `POST /households/{household_id}/completed-work`
- `POST /households/{household_id}/natural-language`
- `GET /households/{household_id}/contributions`

Task listing can be filtered by lifecycle, scheduled or unscheduled state, and
participant. Task details include direct Subtasks, participants, and linked Time
Blocks. Cancelling a planned Time Block leaves its Task available for rescheduling,
and Task completion or reopening is always explicit.

The natural-language route currently recognizes a deliberately small set of English
phrases for completed work, planned work, and unscheduled Tasks. It is an early
end-to-end test surface, not yet a general AI interpreter. A model-backed interpreter
can replace it without changing the Application API's household rules.

During this first development stage, the authenticated caller is represented by the `X-Actor-User-Id` header. OAuth will replace this temporary mechanism before the API is publicly exposed.

Every write also requires an `Idempotency-Key` header. Retrying the same request with
the same key returns the original response without creating duplicate records. A key
must not be reused for different request content.

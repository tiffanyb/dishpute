# Dishpute

Dishpute is a shared household planning and workload application. It tracks future work, reserved time, completed work, and each member's contribution without treating the household as a management hierarchy.

The project is currently being developed from the database upward. See [the architecture document](docs/architecture.md) for product and system decisions.

## Current scope

- Python SQLAlchemy models
- Alembic database migrations
- PostgreSQL development environment
- Python model and database-integrity tests
- Client-neutral MCP Gateway for Codex, Claude, and ChatGPT

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

Start the local server with `make api-dev`. Open `http://127.0.0.1:8000/` for the
Dishpute web app or `http://127.0.0.1:8000/docs` for the interactive API contract.

The API and web app support email signup and login with Argon2 password hashing,
bearer sessions, household creation, and expiring single-use household invitations.

The initial routes are:

- `POST /auth/signup`
- `POST /auth/login`
- `GET /me`
- `POST /households`
- `POST /households/{household_id}/invites`
- `POST /households/join`
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
- `GET /households/{household_id}/members`
- `GET /households/{household_id}/calendar-items`
- `GET /households/{household_id}/work-items`

Task listing can be filtered by lifecycle, scheduled or unscheduled state, and
participant. Task details include direct Subtasks, participants, and linked Time
Blocks. Cancelling a planned Time Block leaves its Task available for rescheduling,
and Task completion or reopening is always explicit.

Calendar items provide planned and completed Time Blocks over a requested date range.
The unified work-item feed contains both Tasks and completed work, allowing completed
work to appear in the Tasks tab without creating a fake future Task. Work may be
scoped as `household` or `personal`; personal completed work defaults to not counting
toward household fairness.

The natural-language route currently recognizes a deliberately small set of English
phrases for completed work, planned work, and unscheduled Tasks. It is an early
end-to-end test surface, not yet a general AI interpreter. A model-backed interpreter
can replace it without changing the Application API's household rules.

Authenticated calls use `Authorization: Bearer <session-token>`. The temporary
`X-Actor-User-Id` development header remains enabled by default for local fixtures and
can be disabled with `DISHPUTE_ALLOW_DEV_ACTOR_HEADER=false`. It must be disabled on a
public deployment. OAuth will protect the remote MCP endpoint separately.

Every write also requires an `Idempotency-Key` header. Retrying the same request with
the same key returns the original response without creating duplicate records. A key
must not be reused for different request content.

## MCP Gateway

The MCP Gateway exposes Dishpute actions as standard Streamable HTTP tools. It is
client-neutral: Codex, Claude, and ChatGPT can use the same gateway once it is hosted
at a public HTTPS address and protected by OAuth.

For local development, first run the Application API. In a second terminal, provide
the local member context and start the gateway:

```bash
DISHPUTE_API_URL=http://127.0.0.1:8000 \
DISHPUTE_HOUSEHOLD_ID=<household-id> \
DISHPUTE_USER_ID=<user-id> \
DISHPUTE_TIMEZONE=America/Phoenix \
make mcp-dev
```

The local MCP endpoint is `http://127.0.0.1:8001/mcp`. The available tools record
completed work, create and update Tasks, schedule or move Time Blocks, explicitly
complete Tasks, and read the Calendar and unified work-item feed. Local IDs in
environment variables are temporary; the remote gateway will derive member context
from OAuth instead.

# Dishpute

Dishpute is a shared household planning and workload application. It tracks future work, reserved time, completed work, and each member's contribution without treating the household as a management hierarchy.

The project is currently being developed from the database upward. See [the architecture document](docs/architecture.md) for product and system decisions.

## Current scope

- PostgreSQL development environment
- Initial relational schema
- Database-level integrity tests

Application API, Remote MCP Gateway, and Web App implementation will follow after the schema is reviewed.

## Local database

1. Copy `.env.example` to `.env` and choose a local development password.
2. Start PostgreSQL with `docker compose up -d database`.
3. Apply the migration with `make db-migrate`.
4. Run database verification with `make db-test`.

The database port is exposed only on the loopback interface for local development.


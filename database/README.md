# Database

Dishpute uses PostgreSQL through Python SQLAlchemy models and Alembic migrations. The models are the primary readable definition of the stored information and relationships.

## Files

- `src/dishpute/models.py` defines tables, fields, relationships, and ordinary constraints in Python.
- `database/alembic/versions/` contains generated Python migrations.
- `tests/test_models.py` verifies household behavior through Python objects.
- Small PostgreSQL-specific functions and reporting views live in the Alembic migration because SQLAlchemy cannot express them directly.

## Design rules

- Every household-owned row includes `household_id`.
- Composite foreign keys prevent a row from referencing a member or record from another household.
- `created_by_user_id` preserves authorship while participant tables represent who plans to participate or completed the work.
- Tasks, Time Blocks, Task Instances, and Completion Records can have multiple participants.
- Tasks and Time Blocks can exist independently and are connected through `time_block_tasks`.
- Tasks support an arbitrary-depth parent and Subtask hierarchy without cycles.
- Completion duration is calculated from start and end times unless a manual override is present.
- Every Completion Record participant receives its full effective duration in contribution reporting.
- Audit Events are append-only.
- Integration request keys prevent repeated MCP calls from applying the same write twice.

## Migration policy

Applied Alembic revisions are immutable. Change the SQLAlchemy models, generate a new revision, review it, and then apply it with `make db-migrate`.

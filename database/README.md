# Database

Dishpute uses standard PostgreSQL. Migrations are intentionally independent of an application framework or hosting provider.

## Design rules

- Every household-owned row includes `household_id`.
- Composite foreign keys prevent a row from referencing a member or record from another household.
- `created_by_user_id`, `planned_for_user_id`, and `completed_by_user_id` represent different facts.
- Tasks and Time Blocks can exist independently and are connected through `time_block_tasks`.
- Completion Records are the source for contribution-duration reporting.
- Audit Events are append-only.
- Integration request keys prevent repeated MCP calls from applying the same write twice.

## Migration policy

Applied migration files are immutable. Schema changes must be introduced in a new numbered migration.


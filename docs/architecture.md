# Dishpute: Product and System Architecture

Status: Approved initial architecture; database implementation in progress

## 1. Product purpose

Dishpute is a shared household planning and workload system. It is intended to help a household:

1. Prevent household work from being forgotten.
2. Protect each member's work-life balance.
3. Make the distribution of household work visible and feel fair over time.

The product is not primarily a conventional to-do list. It treats both the work itself and the time spent on that work as important parts of the domain.

## 2. Product principles

- Planning-first: users may plan a week in advance and adjust it as life changes.
- Flexible detail: users may record a detailed task or only a category and duration.
- Dynamic fairness: fairness is evaluated over time and is not defined as a rigid 50/50 split.
- Independent tasks and time: a task can exist before a planned participant or scheduled time is chosen, and a time block can exist before tasks are placed in it.
- Household privacy by design: household data is shared among household members and isolated from other households.
- Client-independent domain: the core system must work through the web app, MCP clients, and future clients without duplicating business rules.

## 3. Core domain model

### Task

A Task represents something that may need to be done. It may exist without a planned participant, due date, or Time Block.

Examples:

- Clean the storage room.
- Buy groceries.
- Prepare documents for a school application.

A Task has its own lifecycle, such as active, completed, or cancelled. Whether it has been scheduled should normally be derived from its active Time Block relationships instead of being mixed into the lifecycle status.

A Task may contain Subtasks to any depth. Every Subtask is also a Task, and a Task may have no more than one direct parent. The hierarchy may not contain cycles. Completing all Subtasks does not automatically complete their parent; a member must explicitly complete the parent Task.

### Time Block

A Time Block represents reserved or actual household-work time. It is a first-class entity with its own identity, participant, start and end times, status, and lifecycle.

A Time Block may contain zero, one, or multiple Tasks. It may be created as a general household-work reservation before the household decides what work will happen during that period.

Tasks and Time Blocks may each include multiple participating Household members.

### Task and Time Block relationship

Tasks and Time Blocks have an optional many-to-many relationship:

```text
Task --< TimeBlockTask >-- TimeBlock
```

This supports:

- Unscheduled Tasks.
- Empty Time Blocks reserved for household work.
- A Task completed across several Time Blocks.
- Several small Tasks completed within one Time Block.
- Rescheduling or deleting a Time Block without deleting the Task.

### Task Instance

A Task Instance represents one concrete occurrence of a Task, especially for recurring work. For example, "laundry" may be the reusable Task definition, while "laundry for the week of September 7" is a Task Instance.

### Completion Record

A Completion Record captures what actually happened. Planned time and actual work should remain distinguishable so that the system can support planning without requiring perfect real-time tracking.

A Completion Record may include multiple participants. Each participant receives the full effective duration as their individual contribution. For example, two members working together for 60 minutes produce 120 total person-minutes.

Actual duration is normally calculated from start and end times. A manually entered duration overrides the calculated duration.

### Household and membership

Every household-owned record must belong to a Household. Users gain access through Household Membership rather than through direct database access.

Every Household has an editable default timezone used for calendar interpretation and date-based reporting.

## 4. Initial data entities

The initial relational model is expected to include:

- `households`
- `users`
- `household_memberships`
- `tasks`
- `task_instances`
- `time_blocks`
- `time_block_tasks`
- `recurrence_rules`
- `completion_records`
- `audit_events`

Python SQLAlchemy models are the readable source of truth for tables, fields, and relationships. Alembic migrations apply those models to PostgreSQL. Small PostgreSQL-specific protections and reporting views may remain in migrations when the ORM cannot express them directly. Operational retention rules remain deferred until deployment planning.

## 5. Privacy and sharing model

The Household is the sharing and authorization boundary.

- Every Task, Task Instance, Time Block, Completion Record, and related record belongs to one Household.
- Every active member of a Household can see all records that belong to that Household.
- Dishpute does not support records that are private from other members of the same Household.
- Records from one Household must never be visible to members of another Household.
- All completed household work contributes to that Household's fairness statistics.

Work purpose is separate from visibility. `household` work normally contributes to
fairness. `personal` work is still shared within the Household for calendar and
work-life-balance visibility, but does not contribute by default. A Completion Record
stores the explicit fairness-inclusion decision so history remains stable if the
default policy changes later.

Privacy efforts therefore focus on protecting the Household from outside access, including other households, unauthenticated users, infrastructure operators, and unnecessary third-party disclosure.

## 6. System boundaries

The target architecture separates domain behavior from clients and integrations:

```text
Web App -------------------------------> Dishpute Application API ---> PostgreSQL
Codex -----> Remote MCP Gateway -------> Dishpute Application API
ChatGPT ---> Remote MCP Gateway -------> Dishpute Application API
Claude ----> Remote MCP Gateway -------> Dishpute Application API
```

### Application API

The Application API owns authorization and business rules. It is the only supported path for clients and integrations to mutate household data. Browsers and MCP tools must not receive database administrator credentials or issue arbitrary SQL.

### Remote MCP Gateway

The Remote MCP Gateway is a publicly reachable, client-neutral integration adapter
shared by ChatGPT, Codex, and Claude clients. It presents narrow, structured tools to
AI clients and translates approved tool calls into Dishpute API requests.

Each person connects through their own authenticated identity. The gateway resolves that identity to an active Household Membership before allowing access to Household records. A client never chooses an unrestricted `household_id`, and possession of the public gateway URL does not grant access.

Candidate tools include:

- `record_household_work`
- `create_task`
- `schedule_task`
- `list_unscheduled_tasks`
- `get_weekly_household_plan`
- `reschedule_time_block`
- `mark_task_completed`

Write operations must support authentication, household authorization, validation, idempotency, and audit logging.

MCP write access follows these initial rules:

- A member may create a new Task and plan it for themselves or another member without explicit confirmation.
- A member may record newly completed work as completed by themselves or another member without explicit confirmation.
- An active Household member may update shared Tasks, Task Instances, Time Blocks, and Completion Records in that Household, regardless of which member created them.
- MCP may not add, remove, invite, or change the role of a Household member.
- Every record must preserve who created it and, when applicable, who it is planned for or who completed the work.
- Every MCP write must produce an Audit Event containing the authenticated actor, action, target, timestamp, and relevant before-and-after values.
- Every MCP write must use idempotency protection.

Household membership and security-sensitive account changes require a separate administrative workflow outside ordinary MCP tools.

### Plugin

A future plugin may package the Remote MCP Gateway integration together with usage guidance, installation metadata, and optional UI. The plugin is a distribution layer, not the owner of Dishpute's domain rules.

## 7. Database and deployment direction

The data model should use standard PostgreSQL and avoid depending on a single hosting vendor's proprietary behavior.

The database and internal Application API may remain self-hosted and private, but ChatGPT and separate Codex clients require a publicly reachable Remote MCP Gateway. Only the gateway should be exposed publicly; PostgreSQL must not be publicly reachable. The architecture should retain the ability to move to a managed PostgreSQL provider later without redesigning the domain model.

The public gateway requires HTTPS, per-user authentication, short-lived authorization, Household Membership checks on every request, rate limiting, input validation, idempotency, revocation, and security audit logging.

Self-hosting does not by itself guarantee privacy. The operational plan must eventually cover:

- Security updates.
- HTTPS and network access.
- Authentication and secrets.
- Encrypted backups and recovery tests.
- Database isolation.
- Audit-log sensitivity and retention.

Dishpute currently has no product-specific backup, recovery, or data-retention requirements. These operational policies are deferred and do not block initial development. Appropriate baseline policies must be selected before the system stores real household data in production.

## 8. AI privacy consideration

When a user describes household work to an AI client, that content is processed by the AI service before the MCP tool is called. Self-hosting Dishpute protects the storage and application boundary but does not make information disclosed to the AI client invisible to that provider.

Users may choose to provide less detail to an AI client, but any record ultimately stored in Dishpute is visible to all members of its Household.

## 9. Record creation rules

Dishpute uses the following rules to decide what information to create or update:

- Future work creates a Task.
- Reserved household-work time creates a Time Block.
- Scheduling a Task connects that Task to a Time Block.
- A recurring Task creates a specific Task Instance for the relevant date or period.
- Work that has already happened creates a Completion Record and records the actual time spent.
- If completed work matches an existing Task or Task Instance, Dishpute links the Completion Record and marks that work completed.
- If completed work does not match existing work, Dishpute records the completion without creating a new future Task.

## 10. Fairness measurement

The initial fairness measurement is the sum of actual completed household-work duration for each Household member over a selected time period.

```text
member contribution = sum of completed duration for that member
```

Planned or reserved time does not count until the work is recorded as completed. Cancelled, skipped, or uncompleted work does not count.

This measurement is an initial policy, not a permanent definition of fairness. The underlying work history must remain independent from the calculation so that the policy can change without rewriting Tasks, Time Blocks, or Completion Records.

Future versions may allow each Household to select or configure a fairness policy based on duration, responsibility, frequency, perceived effort, category, or a combination. Fairness results should therefore be calculated from source records and a versioned policy rather than stored as an unchangeable score on individual records.

## 11. Decisions made

- The Dishpute folder is the Git repository root.
- Task and Time Block are both first-class entities.
- A Task does not require a planned participant, Time Block, or scheduled time when created.
- Task-Time Block association is optional and many-to-many.
- The core business logic belongs in the Application API.
- MCP is the preferred first AI integration adapter.
- ChatGPT and multiple Codex clients connect through a public Remote MCP Gateway.
- A plugin may package the integration later.
- PostgreSQL is the intended relational database, independent of hosting provider.
- The Household is the sharing boundary; there are no records hidden from other members of the same Household.
- All completed work contributes to household fairness statistics.
- Record creation follows the rules in Section 9.
- The initial fairness measurement is each member's total completed duration within a selected time period.
- Fairness policy is kept separate from the underlying household-work records so it can evolve and eventually vary by Household.
- Tasks support a recursive parent and Subtask hierarchy, and parent completion is always explicit.
- Tasks, Time Blocks, and completed-work sessions may have multiple participants.
- Each participant in a completed-work session receives its full effective duration as contribution.
- A Household has an editable default timezone.
- Actual duration is calculated from start and end times unless a manual override is provided.
- MCP may create new Tasks planned for any member of the caller's Household and may record work completed by any member without explicit confirmation.
- Active Household members may update shared Household records through MCP regardless of who created them.
- Household membership cannot be managed through MCP.
- Product-specific backup, recovery, and data-retention policies are deferred until deployment planning.

## 12. Open design questions

There are no unresolved questions that block the initial architecture or database design.

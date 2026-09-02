# Dishpute Web App Roadmap

This roadmap prioritizes a complete household web experience. AI clients, the remote
MCP gateway, and public deployment are intentionally paused until the usable MVP is
complete.

## Usable MVP

### Household members

- [x] Add a Household view that lists every active member.
- [x] Show member names consistently anywhere work participants appear.
- [ ] Show who created a Task, who plans to participate, and who completed work.
- [x] Let a member generate and copy a single-use household invitation.
- [ ] Let a signed-in member join a household using an invitation.
- [ ] Let members update their own display name.
- [ ] Use collaborative labels such as `Planned with` and `Completed by`.

### Tasks

- [ ] Create a Task from the Tasks view.
- [ ] Capture title, description, category, and household or personal scope.
- [ ] Select zero, one, or multiple planned participants.
- [ ] Optionally schedule a Time Block while creating a Task.
- [ ] Create a Subtask beneath an existing Task.
- [ ] Open a complete Task detail view.
- [ ] Edit Task content, scope, and planned participants.
- [ ] Explicitly complete, reopen, or cancel a Task.
- [ ] Preserve completed and cancelled Tasks in history.
- [ ] Display recursive Subtasks as a navigable hierarchy.

### Time Blocks

- [ ] Create a standalone planned Time Block from Calendar.
- [ ] Schedule an existing Task from Calendar or Task details.
- [ ] Capture date, start time, end time, title, and planned participants.
- [ ] Support multiple Time Blocks for one Task.
- [ ] Move or resize a planned Time Block.
- [ ] Cancel a Time Block without deleting its Task.

### Completed work

- [ ] Record completed work without requiring an existing Task.
- [ ] Capture start and end times or a manually entered duration.
- [ ] Select one or multiple members under `Completed by`.
- [ ] Optionally associate completed work with an existing Task.
- [ ] Control whether completed work counts toward household fairness.
- [ ] Optionally mark the associated Task completed.

### Calendar

- [ ] Add work from a Calendar date or time slot.
- [ ] Clearly distinguish planned and completed items.
- [ ] Filter by member, category, and work scope.
- [ ] Inspect and edit an item from Calendar.
- [ ] Provide day and week views; consider month view after MVP use.
- [ ] Keep today and adjacent-period navigation ergonomic.

### Work list

- [ ] Distinguish Tasks from unmatched completed work.
- [ ] Filter active, completed, cancelled, scheduled, and unscheduled work.
- [ ] Filter by participant, creator, category, and work scope.
- [ ] Search titles and descriptions.
- [ ] Group Subtasks beneath their parents.
- [ ] Sort by creation date, planned time, status, or duration.

### Household overview

- [ ] Edit the household name and default timezone.
- [ ] Show a basic contribution summary for each member.
- [ ] Calculate the initial fairness measure as qualifying completed minutes per member.

### Account and quality

- [ ] Add explicit sign-out and current-session feedback.
- [ ] Let a member change their password.
- [ ] Complete loading, empty, validation, and error states.
- [ ] Confirm destructive actions.
- [ ] Verify keyboard, screen-reader, mobile, and desktop behavior.
- [ ] Add browser-level tests for critical user journeys.

## After MVP

### Recurring work

- [ ] Create daily, weekly, monthly, yearly, and custom recurrence rules.
- [ ] Generate future Task occurrences without duplicating completed history.
- [ ] Edit one occurrence or the whole series.
- [ ] Pause or end a recurrence.

### Weekly planning

- [ ] Add an unscheduled-work queue.
- [ ] Drag Tasks onto Calendar to reserve time.
- [ ] Detect overlapping Time Blocks.
- [ ] Carry unfinished Tasks into a future planning period.
- [ ] Compare planned and completed duration.

### Flexible fairness

- [ ] Add contribution date ranges and category breakdowns.
- [ ] Compare household and personal work.
- [ ] Compare planned and actual contribution.
- [ ] Support household-specific fairness formulas without rewriting work history.

### Data management

- [ ] Define backup, recovery, and retention requirements.
- [ ] Export household data in a portable format.
- [ ] Add account recovery after an email-delivery provider is selected.

## Delivery Order

1. Household member view and invitation workflow.
2. Task creation, detail, editing, and lifecycle controls.
3. Time Block creation and editing from Calendar.
4. Completed-work entry.
5. Recursive Task hierarchy.
6. Search, filters, and weekly planning improvements.
7. Recurring work.
8. Fairness dashboard.
9. Account settings and usability hardening.

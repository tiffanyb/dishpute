from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, exists, select, text
from sqlalchemy.orm import Session

from dishpute.models import (
    AuditEvent,
    CompletionRecord,
    CompletionRecordParticipant,
    HouseholdMembership,
    Task,
    TaskParticipant,
    TimeBlock,
    TimeBlockParticipant,
    TimeBlockTask,
)


class ApplicationError(Exception):
    status_code = 400


class AccessDeniedError(ApplicationError):
    status_code = 403


class RecordNotFoundError(ApplicationError):
    status_code = 404


class ConflictError(ApplicationError):
    status_code = 409


@dataclass(frozen=True)
class CreatedTask:
    task: Task
    participant_user_ids: list[UUID]
    time_block: TimeBlock | None


@dataclass(frozen=True)
class RecordedWork:
    completion: CompletionRecord
    participant_user_ids: list[UUID]
    time_block: TimeBlock | None
    effective_duration_minutes: int


@dataclass(frozen=True)
class Contribution:
    user_id: UUID
    contribution_day: date
    duration_minutes: int


@dataclass(frozen=True)
class ListedTask:
    task: Task
    participant_user_ids: list[UUID]
    scheduled: bool


@dataclass(frozen=True)
class ListedTimeBlock:
    time_block: TimeBlock
    participant_user_ids: list[UUID]


@dataclass(frozen=True)
class TaskDetails:
    task: Task
    participant_user_ids: list[UUID]
    scheduled: bool
    subtasks: list[ListedTask]
    time_blocks: list[ListedTimeBlock]


def _require_active_membership(session: Session, household_id: UUID, user_id: UUID) -> None:
    membership = session.get(HouseholdMembership, (household_id, user_id))
    if membership is None or membership.status != "active":
        raise AccessDeniedError("The user is not an active member of this Household")


def _require_active_participants(
    session: Session, household_id: UUID, participant_user_ids: list[UUID]
) -> list[UUID]:
    unique_ids = list(dict.fromkeys(participant_user_ids))
    if not unique_ids:
        return []

    active_ids = set(
        session.scalars(
            select(HouseholdMembership.user_id).where(
                HouseholdMembership.household_id == household_id,
                HouseholdMembership.user_id.in_(unique_ids),
                HouseholdMembership.status == "active",
            )
        )
    )
    if active_ids != set(unique_ids):
        raise AccessDeniedError("Every participant must be an active Household member")
    return unique_ids


def _find_task(session: Session, household_id: UUID, task_id: UUID) -> Task:
    task = session.scalar(select(Task).where(Task.household_id == household_id, Task.id == task_id))
    if task is None:
        raise RecordNotFoundError("Task was not found in this Household")
    return task


def _find_time_block(session: Session, household_id: UUID, time_block_id: UUID) -> TimeBlock:
    time_block = session.scalar(
        select(TimeBlock).where(
            TimeBlock.household_id == household_id,
            TimeBlock.id == time_block_id,
        )
    )
    if time_block is None:
        raise RecordNotFoundError("Time Block was not found in this Household")
    return time_block


def _task_participant_ids(session: Session, task_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(TaskParticipant.user_id)
            .where(TaskParticipant.task_id == task_id)
            .order_by(TaskParticipant.created_at, TaskParticipant.user_id)
        )
    )


def _time_block_participant_ids(session: Session, time_block_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(TimeBlockParticipant.user_id)
            .where(TimeBlockParticipant.time_block_id == time_block_id)
            .order_by(TimeBlockParticipant.created_at, TimeBlockParticipant.user_id)
        )
    )


def _task_is_scheduled(session: Session, task_id: UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    TimeBlockTask.task_id == task_id,
                    TimeBlockTask.time_block_id == TimeBlock.id,
                    TimeBlock.block_kind == "planned",
                    TimeBlock.status == "planned",
                )
            )
        )
    )


def _audit(
    session: Session,
    household_id: UUID,
    actor_user_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    *,
    before_values: dict[str, object] | None = None,
    after_values: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            household_id=household_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_values=before_values,
            after_values=after_values,
        )
    )


def create_task(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    title: str,
    description: str | None = None,
    category: str = "other",
    participant_user_ids: list[UUID] | None = None,
    parent_task_id: UUID | None = None,
    scheduled_start: datetime | None = None,
    scheduled_end: datetime | None = None,
) -> CreatedTask:
    _require_active_membership(session, household_id, actor_user_id)
    participant_ids = _require_active_participants(
        session, household_id, participant_user_ids or []
    )
    if parent_task_id is not None:
        _find_task(session, household_id, parent_task_id)

    task = Task(
        household_id=household_id,
        created_by_user_id=actor_user_id,
        parent_task_id=parent_task_id,
        title=title.strip(),
        description=description,
        category=category.strip(),
    )
    session.add(task)
    session.flush()

    for participant_id in participant_ids:
        session.add(
            TaskParticipant(
                household_id=household_id,
                task_id=task.id,
                user_id=participant_id,
            )
        )

    _audit(
        session,
        household_id,
        actor_user_id,
        "create",
        "task",
        task.id,
        after_values={
            "title": task.title,
            "parent_task_id": str(parent_task_id) if parent_task_id else None,
        },
    )

    time_block = None
    if scheduled_start is not None and scheduled_end is not None:
        time_block = TimeBlock(
            household_id=household_id,
            created_by_user_id=actor_user_id,
            block_kind="planned",
            status="planned",
            title=task.title,
            starts_at=scheduled_start,
            ends_at=scheduled_end,
        )
        session.add(time_block)
        session.flush()
        for participant_id in participant_ids:
            session.add(
                TimeBlockParticipant(
                    household_id=household_id,
                    time_block_id=time_block.id,
                    user_id=participant_id,
                )
            )
        session.add(
            TimeBlockTask(
                household_id=household_id,
                time_block_id=time_block.id,
                task_id=task.id,
            )
        )
        _audit(
            session,
            household_id,
            actor_user_id,
            "create",
            "time_block",
            time_block.id,
            after_values={"task_id": str(task.id), "status": "planned"},
        )

    session.flush()
    return CreatedTask(task=task, participant_user_ids=participant_ids, time_block=time_block)


def list_tasks(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    lifecycle_status: str | None = None,
    schedule_status: str | None = None,
    participant_user_id: UUID | None = None,
) -> list[ListedTask]:
    _require_active_membership(session, household_id, actor_user_id)
    statement = select(Task).where(Task.household_id == household_id)
    if lifecycle_status is not None:
        statement = statement.where(Task.lifecycle_status == lifecycle_status)
    if participant_user_id is not None:
        statement = statement.where(
            exists().where(
                TaskParticipant.task_id == Task.id,
                TaskParticipant.user_id == participant_user_id,
            )
        )
    if schedule_status is not None:
        scheduled = exists().where(
            TimeBlockTask.task_id == Task.id,
            TimeBlockTask.time_block_id == TimeBlock.id,
            TimeBlock.block_kind == "planned",
            TimeBlock.status == "planned",
        )
        statement = statement.where(scheduled if schedule_status == "scheduled" else ~scheduled)

    tasks = list(session.scalars(statement.order_by(Task.created_at, Task.id)))
    return [
        ListedTask(
            task=task,
            participant_user_ids=_task_participant_ids(session, task.id),
            scheduled=_task_is_scheduled(session, task.id),
        )
        for task in tasks
    ]


def get_task_details(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    task_id: UUID,
) -> TaskDetails:
    _require_active_membership(session, household_id, actor_user_id)
    task = _find_task(session, household_id, task_id)
    child_tasks = list(
        session.scalars(
            select(Task)
            .where(Task.household_id == household_id, Task.parent_task_id == task.id)
            .order_by(Task.created_at, Task.id)
        )
    )
    linked_blocks = list(
        session.scalars(
            select(TimeBlock)
            .join(TimeBlockTask, TimeBlockTask.time_block_id == TimeBlock.id)
            .where(
                TimeBlock.household_id == household_id,
                TimeBlockTask.task_id == task.id,
            )
            .order_by(TimeBlock.starts_at, TimeBlock.id)
        )
    )
    return TaskDetails(
        task=task,
        participant_user_ids=_task_participant_ids(session, task.id),
        scheduled=_task_is_scheduled(session, task.id),
        subtasks=[
            ListedTask(
                task=child,
                participant_user_ids=_task_participant_ids(session, child.id),
                scheduled=_task_is_scheduled(session, child.id),
            )
            for child in child_tasks
        ],
        time_blocks=[
            ListedTimeBlock(
                time_block=block,
                participant_user_ids=_time_block_participant_ids(session, block.id),
            )
            for block in linked_blocks
        ],
    )


def update_task(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    task_id: UUID,
    changes: dict[str, object],
) -> TaskDetails:
    _require_active_membership(session, household_id, actor_user_id)
    task = _find_task(session, household_id, task_id)
    before_values: dict[str, object] = {}
    after_values: dict[str, object] = {}

    for field in ("title", "description", "category"):
        if field in changes:
            value = changes[field]
            if isinstance(value, str):
                value = value.strip()
            before_values[field] = getattr(task, field)
            setattr(task, field, value)
            after_values[field] = value

    if "participant_user_ids" in changes:
        requested_ids = changes["participant_user_ids"]
        assert isinstance(requested_ids, list)
        participant_ids = _require_active_participants(session, household_id, requested_ids)
        before_ids = _task_participant_ids(session, task.id)
        session.execute(delete(TaskParticipant).where(TaskParticipant.task_id == task.id))
        for participant_id in participant_ids:
            session.add(
                TaskParticipant(
                    household_id=household_id,
                    task_id=task.id,
                    user_id=participant_id,
                )
            )
        before_values["participant_user_ids"] = [str(value) for value in before_ids]
        after_values["participant_user_ids"] = [str(value) for value in participant_ids]

    _audit(
        session,
        household_id,
        actor_user_id,
        "update",
        "task",
        task.id,
        before_values=before_values,
        after_values=after_values,
    )
    session.flush()
    return get_task_details(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        task_id=task.id,
    )


def schedule_task(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    task_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    participant_user_ids: list[UUID] | None,
) -> ListedTimeBlock:
    _require_active_membership(session, household_id, actor_user_id)
    task = _find_task(session, household_id, task_id)
    requested_ids = (
        participant_user_ids
        if participant_user_ids is not None
        else _task_participant_ids(session, task.id)
    )
    participant_ids = _require_active_participants(session, household_id, requested_ids)
    time_block = TimeBlock(
        household_id=household_id,
        created_by_user_id=actor_user_id,
        block_kind="planned",
        status="planned",
        title=task.title,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    session.add(time_block)
    session.flush()
    session.add(
        TimeBlockTask(
            household_id=household_id,
            time_block_id=time_block.id,
            task_id=task.id,
        )
    )
    for participant_id in participant_ids:
        session.add(
            TimeBlockParticipant(
                household_id=household_id,
                time_block_id=time_block.id,
                user_id=participant_id,
            )
        )
    _audit(
        session,
        household_id,
        actor_user_id,
        "create",
        "time_block",
        time_block.id,
        after_values={"task_id": str(task.id), "status": "planned"},
    )
    session.flush()
    return ListedTimeBlock(time_block=time_block, participant_user_ids=participant_ids)


def update_planned_time_block(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    time_block_id: UUID,
    changes: dict[str, object],
) -> ListedTimeBlock:
    _require_active_membership(session, household_id, actor_user_id)
    time_block = _find_time_block(session, household_id, time_block_id)
    if time_block.block_kind != "planned":
        raise ConflictError("Actual Time Blocks cannot be rescheduled or cancelled")

    starts_at = changes.get("starts_at", time_block.starts_at)
    ends_at = changes.get("ends_at", time_block.ends_at)
    assert isinstance(starts_at, datetime) and isinstance(ends_at, datetime)
    if ends_at <= starts_at:
        raise ApplicationError("ends_at must be after starts_at")

    before_values = {
        field: getattr(time_block, field).isoformat()
        if isinstance(getattr(time_block, field), datetime)
        else getattr(time_block, field)
        for field in changes
    }
    for field, value in changes.items():
        setattr(time_block, field, value)
    after_values = {
        field: value.isoformat() if isinstance(value, datetime) else value
        for field, value in changes.items()
    }
    _audit(
        session,
        household_id,
        actor_user_id,
        "update",
        "time_block",
        time_block.id,
        before_values=before_values,
        after_values=after_values,
    )
    session.flush()
    return ListedTimeBlock(
        time_block=time_block,
        participant_user_ids=_time_block_participant_ids(session, time_block.id),
    )


def update_task_lifecycle(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    task_id: UUID,
    lifecycle_status: str,
) -> TaskDetails:
    _require_active_membership(session, household_id, actor_user_id)
    task = _find_task(session, household_id, task_id)
    before_status = task.lifecycle_status
    now = datetime.now().astimezone()
    task.lifecycle_status = lifecycle_status
    task.completed_at = now if lifecycle_status == "completed" else None
    task.cancelled_at = now if lifecycle_status == "cancelled" else None
    _audit(
        session,
        household_id,
        actor_user_id,
        "update",
        "task",
        task.id,
        before_values={"lifecycle_status": before_status},
        after_values={"lifecycle_status": lifecycle_status},
    )
    session.flush()
    return get_task_details(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        task_id=task.id,
    )


def record_completed_work(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    category: str,
    description: str | None,
    participant_user_ids: list[UUID],
    started_at: datetime | None,
    ended_at: datetime | None,
    duration_override_minutes: int | None,
    task_id: UUID | None = None,
    complete_task: bool = False,
) -> RecordedWork:
    _require_active_membership(session, household_id, actor_user_id)
    participant_ids = _require_active_participants(session, household_id, participant_user_ids)
    if not participant_ids:
        raise ApplicationError("Completed work requires at least one participant")

    task = _find_task(session, household_id, task_id) if task_id is not None else None
    time_block = None
    if started_at is not None and ended_at is not None:
        time_block = TimeBlock(
            household_id=household_id,
            created_by_user_id=actor_user_id,
            block_kind="actual",
            status="completed",
            title=description,
            starts_at=started_at,
            ends_at=ended_at,
        )
        session.add(time_block)
        session.flush()
        for participant_id in participant_ids:
            session.add(
                TimeBlockParticipant(
                    household_id=household_id,
                    time_block_id=time_block.id,
                    user_id=participant_id,
                )
            )
        _audit(
            session,
            household_id,
            actor_user_id,
            "create",
            "time_block",
            time_block.id,
            after_values={"status": "completed", "block_kind": "actual"},
        )

    completion = CompletionRecord(
        household_id=household_id,
        created_by_user_id=actor_user_id,
        task_id=task.id if task is not None else None,
        time_block_id=time_block.id if time_block is not None else None,
        category=category.strip(),
        description=description,
        duration_override_minutes=duration_override_minutes,
        started_at=started_at,
        ended_at=ended_at,
        completed_at=ended_at or datetime.now().astimezone(),
    )
    session.add(completion)
    session.flush()
    for participant_id in participant_ids:
        session.add(
            CompletionRecordParticipant(
                household_id=household_id,
                completion_record_id=completion.id,
                user_id=participant_id,
            )
        )

    if task is not None and complete_task:
        before_status = task.lifecycle_status
        task.lifecycle_status = "completed"
        task.completed_at = completion.completed_at
        _audit(
            session,
            household_id,
            actor_user_id,
            "update",
            "task",
            task.id,
            before_values={"lifecycle_status": before_status},
            after_values={"lifecycle_status": "completed"},
        )

    _audit(
        session,
        household_id,
        actor_user_id,
        "create",
        "completion_record",
        completion.id,
        after_values={
            "task_id": str(task.id) if task is not None else None,
            "participant_user_ids": [str(value) for value in participant_ids],
        },
    )
    session.flush()

    return RecordedWork(
        completion=completion,
        participant_user_ids=participant_ids,
        time_block=time_block,
        effective_duration_minutes=completion.effective_duration_minutes,
    )


def list_contributions(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Contribution]:
    _require_active_membership(session, household_id, actor_user_id)
    conditions = ["household_id = :household_id"]
    parameters: dict[str, object] = {"household_id": household_id}
    if start_date is not None:
        conditions.append("contribution_day >= :start_date")
        parameters["start_date"] = start_date
    if end_date is not None:
        conditions.append("contribution_day <= :end_date")
        parameters["end_date"] = end_date

    rows = session.execute(
        text(
            "SELECT user_id, contribution_day, duration_minutes "
            "FROM member_contribution_durations WHERE "
            + " AND ".join(conditions)
            + " ORDER BY contribution_day, user_id"
        ),
        parameters,
    )
    return [
        Contribution(
            user_id=row.user_id,
            contribution_day=row.contribution_day,
            duration_minutes=row.duration_minutes,
        )
        for row in rows
    ]

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select, text
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
    task = session.scalar(
        select(Task).where(Task.household_id == household_id, Task.id == task_id)
    )
    if task is None:
        raise RecordNotFoundError("Task was not found in this Household")
    return task


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
        after_values={"title": task.title, "parent_task_id": str(parent_task_id) if parent_task_id else None},
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
    participant_ids = _require_active_participants(
        session, household_id, participant_user_ids
    )
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

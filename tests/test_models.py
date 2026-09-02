from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from dishpute.models import (
    AppUser,
    CompletionRecord,
    CompletionRecordParticipant,
    Household,
    HouseholdMembership,
    RecurrenceRule,
    Task,
    TaskInstance,
    TaskParticipant,
    TimeBlock,
    TimeBlockParticipant,
)


def create_household(session: Session) -> tuple[Household, AppUser, AppUser]:
    first_member = AppUser(display_name="First Member")
    second_member = AppUser(display_name="Second Member")
    session.add_all([first_member, second_member])
    session.flush()
    household = Household(
        name="Test Household",
        created_by_user_id=first_member.id,
        default_timezone="America/Phoenix",
    )
    household.memberships = [
        HouseholdMembership(user=first_member),
        HouseholdMembership(user=second_member),
    ]
    session.add(household)
    session.flush()
    return household, first_member, second_member


def test_joint_work_gives_each_participant_the_full_duration(session: Session) -> None:
    household, first_member, second_member = create_household(session)
    task = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Clean together",
        participants=[
            TaskParticipant(household_id=household.id, user=first_member),
            TaskParticipant(household_id=household.id, user=second_member),
        ],
    )
    start = datetime(2026, 9, 5, 17, tzinfo=UTC)
    time_block = TimeBlock(
        household_id=household.id,
        created_by_user_id=first_member.id,
        block_kind="actual",
        status="completed",
        starts_at=start,
        ends_at=start + timedelta(minutes=60),
        participants=[
            TimeBlockParticipant(household_id=household.id, user=first_member),
            TimeBlockParticipant(household_id=household.id, user=second_member),
        ],
    )
    completion = CompletionRecord(
        household_id=household.id,
        created_by_user_id=first_member.id,
        task=task,
        time_block=time_block,
        category="cleaning",
        completed_at=time_block.ends_at,
        participants=[
            CompletionRecordParticipant(household_id=household.id, user=first_member),
            CompletionRecordParticipant(household_id=household.id, user=second_member),
        ],
    )
    session.add(completion)
    session.flush()

    contributions = session.execute(
        text(
            "SELECT user_id, duration_minutes FROM member_contribution_durations "
            "WHERE household_id = :household_id"
        ),
        {"household_id": household.id},
    ).all()

    assert sorted(row.duration_minutes for row in contributions) == [60, 60]
    assert completion.effective_duration_minutes == 60

    completion.duration_override_minutes = 45
    session.flush()
    duration = session.execute(
        text(
            "SELECT duration_minutes FROM completion_record_durations "
            "WHERE completion_record_id = :completion_id"
        ),
        {"completion_id": completion.id},
    ).scalar_one()
    assert duration == 45


def test_task_hierarchy_is_recursive_but_cannot_contain_cycles(session: Session) -> None:
    household, first_member, _ = create_household(session)
    parent = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Prepare for guests",
    )
    child = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Clean the kitchen",
        parent=parent,
    )
    grandchild = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Clean the refrigerator",
        parent=child,
    )
    session.add_all([parent, child, grandchild])
    session.flush()

    grandchild.lifecycle_status = "completed"
    grandchild.completed_at = datetime.now(UTC)
    session.flush()
    assert parent.lifecycle_status == "active"

    with pytest.raises(DBAPIError, match="task hierarchy cannot contain a cycle"):
        with session.begin_nested():
            parent.parent_task_id = grandchild.id
            session.flush()


def test_recurrence_rule_must_belong_to_the_same_task(session: Session) -> None:
    household, first_member, _ = create_household(session)
    recurring_task = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Laundry",
    )
    other_task = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Replace filter",
    )
    session.add_all([recurring_task, other_task])
    session.flush()
    rule = RecurrenceRule(
        household_id=household.id,
        task_id=recurring_task.id,
        frequency="weekly",
        starts_on=datetime(2026, 9, 1).date(),
        timezone=household.default_timezone,
    )
    session.add(rule)
    session.flush()

    wrong_instance = TaskInstance(
        household_id=household.id,
        task_id=other_task.id,
        recurrence_rule_id=rule.id,
        occurrence_date=datetime(2026, 9, 5).date(),
    )
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(wrong_instance)
            session.flush()


def test_household_timezone_must_be_valid(session: Session) -> None:
    household, _, _ = create_household(session)

    with pytest.raises(DBAPIError, match="invalid household timezone"):
        with session.begin_nested():
            household.default_timezone = "Not/A_Real_Timezone"
            session.flush()


def test_household_cannot_reference_an_outside_member(session: Session) -> None:
    household, first_member, _ = create_household(session)
    outsider = AppUser(display_name="Outside Member")
    session.add(outsider)
    session.flush()

    task = Task(
        household_id=household.id,
        created_by_user_id=first_member.id,
        title="Household task",
        participants=[TaskParticipant(household_id=household.id, user=outsider)],
    )
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(task)
            session.flush()

    assert session.scalar(select(Task).where(Task.title == "Household task")) is None

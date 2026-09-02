from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dishpute.models import (
    AppUser,
    AuditEvent,
    Household,
    HouseholdMembership,
    IntegrationRequest,
    Task,
    TimeBlock,
)


def create_family(
    session: Session, name: str = "Test Household"
) -> tuple[Household, AppUser, AppUser]:
    first_member = AppUser(display_name=f"{name} First Member")
    second_member = AppUser(display_name=f"{name} Second Member")
    session.add_all([first_member, second_member])
    session.flush()
    household = Household(
        name=name,
        created_by_user_id=first_member.id,
        default_timezone="America/Phoenix",
        memberships=[
            HouseholdMembership(user=first_member),
            HouseholdMembership(user=second_member),
        ],
    )
    session.add(household)
    session.commit()
    return household, first_member, second_member


def headers(user_id: UUID) -> dict[str, str]:
    return {
        "X-Actor-User-Id": str(user_id),
        "Idempotency-Key": str(uuid4()),
    }


def create_task(
    api_client: TestClient,
    household_id: UUID,
    actor_user_id: UUID,
    title: str,
    **values: object,
) -> dict[str, object]:
    response = api_client.post(
        f"/households/{household_id}/tasks",
        headers=headers(actor_user_id),
        json={"title": title, **values},
    )
    assert response.status_code == 201
    return response.json()


def test_members_can_list_and_inspect_shared_task_hierarchy(
    api_client: TestClient, session: Session
) -> None:
    household, first_member, second_member = create_family(session)
    parent = create_task(api_client, household.id, first_member.id, "Host a party")
    child = create_task(
        api_client,
        household.id,
        second_member.id,
        "Plan the meal",
        parent_task_id=parent["id"],
    )

    task_list = api_client.get(
        f"/households/{household.id}/tasks",
        headers=headers(second_member.id),
        params={"lifecycle_status": "active", "schedule_status": "unscheduled"},
    )
    assert task_list.status_code == 200
    assert {task["title"] for task in task_list.json()} == {
        "Host a party",
        "Plan the meal",
    }

    details = api_client.get(
        f"/households/{household.id}/tasks/{parent['id']}",
        headers=headers(second_member.id),
    )
    assert details.status_code == 200
    assert details.json()["subtasks"] == [
        {
            "id": child["id"],
                "title": "Plan the meal",
                "category": "other",
                "work_scope": "household",
            "lifecycle_status": "active",
            "parent_task_id": parent["id"],
            "participant_user_ids": [],
            "scheduled": False,
        }
    ]


def test_member_can_edit_schedule_reschedule_and_cancel_shared_task_time(
    api_client: TestClient, session: Session
) -> None:
    household, first_member, second_member = create_family(session)
    task = create_task(api_client, household.id, first_member.id, "Clean kitchen")

    update_response = api_client.patch(
        f"/households/{household.id}/tasks/{task['id']}",
        headers=headers(second_member.id),
        json={
            "title": "Clean the kitchen",
            "category": "cleaning",
            "participant_user_ids": [str(first_member.id), str(second_member.id)],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["created_by_user_id"] == str(first_member.id)
    assert set(update_response.json()["participant_user_ids"]) == {
        str(first_member.id),
        str(second_member.id),
    }

    schedule_response = api_client.post(
        f"/households/{household.id}/tasks/{task['id']}/time-blocks",
        headers=headers(second_member.id),
        json={
            "starts_at": "2026-09-10T10:00:00-07:00",
            "ends_at": "2026-09-10T11:00:00-07:00",
        },
    )
    assert schedule_response.status_code == 201
    block = schedule_response.json()
    assert set(block["participant_user_ids"]) == {
        str(first_member.id),
        str(second_member.id),
    }

    scheduled_tasks = api_client.get(
        f"/households/{household.id}/tasks",
        headers=headers(first_member.id),
        params={"schedule_status": "scheduled"},
    ).json()
    assert [item["id"] for item in scheduled_tasks] == [task["id"]]

    rescheduled = api_client.patch(
        f"/households/{household.id}/time-blocks/{block['id']}",
        headers=headers(first_member.id),
        json={
            "starts_at": "2026-09-10T13:00:00-07:00",
            "ends_at": "2026-09-10T14:30:00-07:00",
        },
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["starts_at"] == "2026-09-10T13:00:00-07:00"
    assert rescheduled.json()["ends_at"] == "2026-09-10T14:30:00-07:00"

    cancelled = api_client.patch(
        f"/households/{household.id}/time-blocks/{block['id']}",
        headers=headers(second_member.id),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    response_statuses = list(
        session.scalars(
            select(IntegrationRequest.response_status)
            .where(IntegrationRequest.household_id == household.id)
            .order_by(IntegrationRequest.created_at, IntegrationRequest.operation)
        )
    )
    assert response_statuses.count(201) == 2
    assert response_statuses.count(200) == 3

    unscheduled_tasks = api_client.get(
        f"/households/{household.id}/tasks",
        headers=headers(first_member.id),
        params={"schedule_status": "unscheduled"},
    ).json()
    assert [item["id"] for item in unscheduled_tasks] == [task["id"]]
    assert session.scalar(select(func.count()).select_from(Task)) == 1
    assert session.scalar(select(func.count()).select_from(TimeBlock)) == 1


def test_task_completion_and_reopening_are_explicit_and_audited(
    api_client: TestClient, session: Session
) -> None:
    household, first_member, second_member = create_family(session)
    parent = create_task(api_client, household.id, first_member.id, "Host a party")
    child = create_task(
        api_client,
        household.id,
        second_member.id,
        "Plan the meal",
        parent_task_id=parent["id"],
    )

    completed = api_client.patch(
        f"/households/{household.id}/tasks/{parent['id']}/lifecycle",
        headers=headers(second_member.id),
        json={"lifecycle_status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["lifecycle_status"] == "completed"
    assert completed.json()["subtasks"][0]["lifecycle_status"] == "active"

    reopened = api_client.patch(
        f"/households/{household.id}/tasks/{parent['id']}/lifecycle",
        headers=headers(first_member.id),
        json={"lifecycle_status": "active"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["lifecycle_status"] == "active"
    assert session.get(Task, UUID(child["id"])).lifecycle_status == "active"
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 4


def test_task_management_is_isolated_between_households(
    api_client: TestClient, session: Session
) -> None:
    first_household, first_member, _ = create_family(session, "First Household")
    second_household, second_member, _ = create_family(session, "Second Household")
    task = create_task(api_client, first_household.id, first_member.id, "Private household work")

    response = api_client.get(
        f"/households/{first_household.id}/tasks/{task['id']}",
        headers=headers(second_member.id),
    )

    assert response.status_code == 403
    assert second_household.id != first_household.id

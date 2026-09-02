from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dishpute.models import (
    AppUser,
    AuditEvent,
    CompletionRecord,
    Household,
    HouseholdMembership,
    IntegrationRequest,
    Task,
    TimeBlock,
)


def create_family(session: Session) -> tuple[Household, AppUser, AppUser]:
    tiffany = AppUser(display_name="Tiffany")
    husband = AppUser(display_name="Husband")
    session.add_all([tiffany, husband])
    session.flush()
    household = Household(
        name="Tiffany's Household",
        created_by_user_id=tiffany.id,
        default_timezone="America/Phoenix",
        memberships=[
            HouseholdMembership(user=tiffany),
            HouseholdMembership(user=husband),
        ],
    )
    session.add(household)
    session.commit()
    return household, tiffany, husband


def actor_headers(user_id: UUID, idempotency_key: str | None = None) -> dict[str, str]:
    return {
        "X-Actor-User-Id": str(user_id),
        "Idempotency-Key": idempotency_key or str(uuid4()),
    }


def test_tiffany_records_kitchen_work_that_just_happened(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, _ = create_family(session)

    response = api_client.post(
        f"/households/{household.id}/completed-work",
        headers=actor_headers(tiffany.id),
        json={
            "category": "cleaning",
            "description": "Cleaned the kitchen",
            "participant_user_ids": [str(tiffany.id)],
            "started_at": "2026-09-05T10:00:00-07:00",
            "ended_at": "2026-09-05T11:00:00-07:00",
        },
    )

    assert response.status_code == 201
    assert response.json()["effective_duration_minutes"] == 60
    assert response.json()["task_id"] is None
    assert session.scalar(select(func.count()).select_from(Task)) == 0
    assert session.scalar(select(func.count()).select_from(CompletionRecord)) == 1
    actual_block = session.scalar(select(TimeBlock))
    assert actual_block is not None
    assert actual_block.block_kind == "actual"

    contributions = api_client.get(
        f"/households/{household.id}/contributions",
        headers=actor_headers(tiffany.id),
    )
    assert contributions.status_code == 200
    assert contributions.json()[0]["duration_minutes"] == 60
    assert contributions.json()[0]["user_id"] == str(tiffany.id)


def test_husband_plans_future_kitchen_work(api_client: TestClient, session: Session) -> None:
    household, _, husband = create_family(session)

    response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=actor_headers(husband.id),
        json={
            "title": "Clean the kitchen",
            "participant_user_ids": [str(husband.id)],
            "scheduled_start": "2026-09-06T10:00:00-07:00",
            "scheduled_end": "2026-09-06T11:00:00-07:00",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Clean the kitchen"
    assert body["participant_user_ids"] == [str(husband.id)]
    assert body["time_block_id"] is not None
    planned_block = session.get(TimeBlock, UUID(body["time_block_id"]))
    assert planned_block is not None
    assert planned_block.block_kind == "planned"
    assert planned_block.status == "planned"
    assert session.scalar(select(func.count()).select_from(CompletionRecord)) == 0

    contributions = api_client.get(
        f"/households/{household.id}/contributions",
        headers=actor_headers(husband.id),
    )
    assert contributions.json() == []


def test_tiffany_adds_unscheduled_subtask_to_husbands_task(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, husband = create_family(session)
    parent_response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=actor_headers(husband.id),
        json={"title": "Host a party"},
    )
    assert parent_response.status_code == 201
    parent_id = parent_response.json()["id"]

    child_response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=actor_headers(tiffany.id),
        json={"title": "Plan the meal", "parent_task_id": parent_id},
    )

    assert child_response.status_code == 201
    child = session.get(Task, UUID(child_response.json()["id"]))
    parent = session.get(Task, UUID(parent_id))
    assert child is not None and parent is not None
    assert child.parent_task_id == parent.id
    assert child.created_by_user_id == tiffany.id
    assert parent.created_by_user_id == husband.id
    assert child_response.json()["time_block_id"] is None
    assert session.scalar(select(func.count()).select_from(TimeBlock)) == 0
    assert session.scalar(select(func.count()).select_from(CompletionRecord)) == 0


def test_joint_workflow_completes_task_and_credits_both_members(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, husband = create_family(session)
    task_response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=actor_headers(tiffany.id),
        json={
            "title": "Clean the kitchen together",
            "participant_user_ids": [str(tiffany.id), str(husband.id)],
            "scheduled_start": "2026-09-07T10:00:00-07:00",
            "scheduled_end": "2026-09-07T11:00:00-07:00",
        },
    )
    task_id = task_response.json()["id"]

    completion_response = api_client.post(
        f"/households/{household.id}/completed-work",
        headers=actor_headers(husband.id),
        json={
            "category": "cleaning",
            "description": "Cleaned the kitchen together",
            "participant_user_ids": [str(tiffany.id), str(husband.id)],
            "started_at": "2026-09-07T10:00:00-07:00",
            "ended_at": "2026-09-07T11:00:00-07:00",
            "task_id": task_id,
            "complete_task": True,
        },
    )

    assert completion_response.status_code == 201
    assert completion_response.json()["effective_duration_minutes"] == 60
    task = session.get(Task, UUID(task_id))
    assert task is not None
    assert task.lifecycle_status == "completed"

    contributions = api_client.get(
        f"/households/{household.id}/contributions",
        headers=actor_headers(tiffany.id),
    ).json()
    assert sorted(item["duration_minutes"] for item in contributions) == [60, 60]
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 5


def test_tiffany_records_completed_work_using_natural_language(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, _ = create_family(session)

    response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=actor_headers(tiffany.id),
        json={
            "text": "I just cleaned the kitchen 10:00 to 11:00",
            "reference_date": "2026-09-05",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["interpreted_action"] == "record_completed_work"
    assert body["completed_work"]["effective_duration_minutes"] == 60
    assert body["completed_work"]["participant_user_ids"] == [str(tiffany.id)]
    assert body["task"] is None
    assert session.scalar(select(func.count()).select_from(Task)) == 0


def test_husband_plans_work_using_natural_language(
    api_client: TestClient, session: Session
) -> None:
    household, _, husband = create_family(session)

    response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=actor_headers(husband.id),
        json={
            "text": "I will clean the kitchen 10:00 to 11:00",
            "reference_date": "2026-09-06",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["interpreted_action"] == "create_task"
    assert body["task"]["title"] == "Clean the kitchen"
    assert body["task"]["participant_user_ids"] == [str(husband.id)]
    assert body["task"]["time_block_id"] is not None
    assert body["completed_work"] is None


def test_tiffany_adds_unscheduled_subtask_using_natural_language(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, husband = create_family(session)
    parent_response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=actor_headers(husband.id),
        json={"text": "Host a party", "reference_date": "2026-09-06"},
    )
    parent_id = parent_response.json()["task"]["id"]

    child_response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=actor_headers(tiffany.id),
        json={
            "text": "Plan for the meal",
            "reference_date": "2026-09-06",
            "parent_task_id": parent_id,
        },
    )

    assert child_response.status_code == 201
    child = child_response.json()["task"]
    assert child["title"] == "Plan for the meal"
    assert child["parent_task_id"] == parent_id
    assert child["participant_user_ids"] == []
    assert child["time_block_id"] is None


def test_retried_natural_language_request_does_not_duplicate_work(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, _ = create_family(session)
    headers = actor_headers(tiffany.id, "cleaned-kitchen-once")
    request_body = {
        "text": "I just cleaned the kitchen 10:00 to 11:00",
        "reference_date": "2026-09-08",
    }

    first_response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=headers,
        json=request_body,
    )
    replay_response = api_client.post(
        f"/households/{household.id}/natural-language",
        headers=headers,
        json=request_body,
    )

    assert first_response.status_code == 201
    assert first_response.headers["Idempotency-Replayed"] == "false"
    assert replay_response.status_code == 201
    assert replay_response.headers["Idempotency-Replayed"] == "true"
    assert replay_response.json() == first_response.json()
    assert session.scalar(select(func.count()).select_from(CompletionRecord)) == 1
    assert session.scalar(select(func.count()).select_from(TimeBlock)) == 1
    assert session.scalar(select(func.count()).select_from(IntegrationRequest)) == 1

    contributions = api_client.get(
        f"/households/{household.id}/contributions",
        headers=actor_headers(tiffany.id),
    ).json()
    assert contributions[0]["duration_minutes"] == 60


def test_idempotency_key_cannot_be_reused_for_different_content(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, _ = create_family(session)
    headers = actor_headers(tiffany.id, "one-request-only")

    first_response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=headers,
        json={"title": "Clean the kitchen"},
    )
    conflict_response = api_client.post(
        f"/households/{household.id}/tasks",
        headers=headers,
        json={"title": "Clean the bathroom"},
    )

    assert first_response.status_code == 201
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "detail": "This Idempotency-Key was already used for a different request"
    }
    assert session.scalar(select(func.count()).select_from(Task)) == 1


def test_write_requires_an_idempotency_key(api_client: TestClient, session: Session) -> None:
    household, tiffany, _ = create_family(session)

    response = api_client.post(
        f"/households/{household.id}/tasks",
        headers={"X-Actor-User-Id": str(tiffany.id)},
        json={"title": "Clean the kitchen"},
    )

    assert response.status_code == 422
    assert session.scalar(select(func.count()).select_from(Task)) == 0

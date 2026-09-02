from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from dishpute.models import AppUser, Household, HouseholdMembership


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


def headers(user_id: UUID, *, write: bool = False) -> dict[str, str]:
    values = {"X-Actor-User-Id": str(user_id)}
    if write:
        values["Idempotency-Key"] = str(uuid4())
    return values


def test_personal_completed_work_appears_in_calendar_and_work_items(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, husband = create_family(session)

    recorded = api_client.post(
        f"/households/{household.id}/completed-work",
        headers=headers(tiffany.id, write=True),
        json={
            "category": "professional",
            "description": "Wrote a proposal",
            "work_scope": "personal",
            "participant_user_ids": [str(tiffany.id)],
            "started_at": "2026-09-02T14:00:00-07:00",
            "ended_at": "2026-09-02T15:00:00-07:00",
        },
    )

    assert recorded.status_code == 201
    assert recorded.json()["work_scope"] == "personal"
    assert recorded.json()["counts_toward_fairness"] is False
    assert recorded.json()["task_id"] is None

    calendar = api_client.get(
        f"/households/{household.id}/calendar-items",
        headers=headers(husband.id),
        params={
            "range_start": "2026-09-01T00:00:00-07:00",
            "range_end": "2026-09-08T00:00:00-07:00",
        },
    )
    assert calendar.status_code == 200
    assert calendar.json() == [
        {
            "id": recorded.json()["time_block_id"],
            "item_type": "completed",
            "title": "Wrote a proposal",
            "category": "professional",
            "work_scope": "personal",
            "status": "completed",
            "starts_at": "2026-09-02T21:00:00Z",
            "ends_at": "2026-09-02T22:00:00Z",
            "participant_user_ids": [str(tiffany.id)],
            "task_ids": [],
            "completion_record_id": recorded.json()["completion_record_id"],
            "counts_toward_fairness": False,
        }
    ]

    work_items = api_client.get(
        f"/households/{household.id}/work-items",
        headers=headers(tiffany.id),
    )
    assert work_items.status_code == 200
    assert work_items.json() == [
        {
            "id": recorded.json()["completion_record_id"],
            "item_type": "completed_work",
            "title": "Wrote a proposal",
            "category": "professional",
            "work_scope": "personal",
            "status": "completed",
            "participant_user_ids": [str(tiffany.id)],
            "parent_task_id": None,
            "starts_at": "2026-09-02T21:00:00Z",
            "ends_at": "2026-09-02T22:00:00Z",
            "duration_minutes": 60,
            "counts_toward_fairness": False,
        }
    ]

    contributions = api_client.get(
        f"/households/{household.id}/contributions",
        headers=headers(tiffany.id),
    )
    assert contributions.json() == []


def test_planned_personal_task_and_members_support_web_app_views(
    api_client: TestClient, session: Session
) -> None:
    household, tiffany, husband = create_family(session)
    created = api_client.post(
        f"/households/{household.id}/tasks",
        headers=headers(tiffany.id, write=True),
        json={
            "title": "Draft project brief",
            "category": "professional",
            "work_scope": "personal",
            "participant_user_ids": [str(tiffany.id)],
            "scheduled_start": "2026-09-03T09:00:00-07:00",
            "scheduled_end": "2026-09-03T10:00:00-07:00",
        },
    )
    assert created.status_code == 201

    calendar = api_client.get(
        f"/households/{household.id}/calendar-items",
        headers=headers(husband.id),
        params={
            "range_start": "2026-09-03T00:00:00-07:00",
            "range_end": "2026-09-04T00:00:00-07:00",
        },
    ).json()
    assert calendar[0]["item_type"] == "planned"
    assert calendar[0]["work_scope"] == "personal"
    assert calendar[0]["task_ids"] == [created.json()["id"]]

    work_items = api_client.get(
        f"/households/{household.id}/work-items",
        headers=headers(husband.id),
    ).json()
    assert work_items[0]["item_type"] == "task"
    assert work_items[0]["title"] == "Draft project brief"
    assert work_items[0]["work_scope"] == "personal"

    members = api_client.get(
        f"/households/{household.id}/members",
        headers=headers(tiffany.id),
    )
    assert members.status_code == 200
    assert {member["display_name"] for member in members.json()} == {
        "Tiffany",
        "Husband",
    }

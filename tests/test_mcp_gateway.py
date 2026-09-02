import json
from datetime import date, time
from uuid import UUID, uuid4

import httpx
import pytest

from dishpute.mcp_gateway import DishputeApiClient, build_mcp

HOUSEHOLD_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")


def mock_client(handler: httpx.MockTransport) -> DishputeApiClient:
    return DishputeApiClient(
        base_url="http://dishpute.test",
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        timezone_name="America/Phoenix",
        transport=handler,
    )


@pytest.mark.anyio
async def test_mcp_exposes_client_neutral_household_tools() -> None:
    server = build_mcp(
        mock_client(httpx.MockTransport(lambda _request: httpx.Response(200, json={})))
    )

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "record_work",
        "create_task",
        "list_work_items",
        "get_calendar",
        "update_task",
        "schedule_task",
        "reschedule_time_block",
        "complete_task",
    }
    assert tools["list_work_items"].annotations.readOnlyHint is True
    assert tools["get_calendar"].annotations.readOnlyHint is True
    assert tools["record_work"].annotations.readOnlyHint is False


@pytest.mark.anyio
async def test_record_work_tool_calls_application_api_with_local_timezone() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "completion_record_id": str(uuid4()),
                "time_block_id": str(uuid4()),
                "task_id": None,
                "participant_user_ids": [str(USER_ID)],
                "effective_duration_minutes": 60,
                "work_scope": "personal",
                "counts_toward_fairness": False,
            },
        )

    server = build_mcp(mock_client(httpx.MockTransport(handle)))
    _content, result = await server.call_tool(
        "record_work",
        {
            "title": "Wrote a proposal",
            "work_date": date(2026, 9, 2),
            "start_time": time(14, 0),
            "end_time": time(15, 0),
            "category": "professional",
            "work_scope": "personal",
        },
    )

    assert isinstance(result, dict)
    assert result["effective_duration_minutes"] == 60
    assert captured["method"] == "POST"
    assert captured["path"] == f"/households/{HOUSEHOLD_ID}/completed-work"
    assert captured["body"] == {
        "category": "professional",
        "description": "Wrote a proposal",
        "work_scope": "personal",
        "counts_toward_fairness": None,
        "participant_user_ids": [str(USER_ID)],
        "started_at": "2026-09-02T14:00:00-07:00",
        "ended_at": "2026-09-02T15:00:00-07:00",
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-actor-user-id"] == str(USER_ID)
    assert UUID(headers["idempotency-key"])


@pytest.mark.anyio
async def test_calendar_tool_uses_an_exclusive_date_range() -> None:
    captured: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    server = build_mcp(mock_client(httpx.MockTransport(handle)))
    content, result = await server.call_tool(
        "get_calendar",
        {"range_start": date(2026, 9, 1), "range_end": date(2026, 9, 8)},
    )

    assert content == []
    assert result == {"result": []}
    assert captured == {
        "range_start": "2026-09-01T00:00:00-07:00",
        "range_end": "2026-09-08T00:00:00-07:00",
    }

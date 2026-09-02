import os
from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


class DishputeApiError(RuntimeError):
    pass


class DishputeApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        household_id: UUID,
        user_id: UUID,
        timezone_name: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.household_id = household_id
        self.user_id = user_id
        self.timezone = ZoneInfo(timezone_name)
        self.transport = transport

    @classmethod
    def from_environment(cls) -> "DishputeApiClient":
        required = {
            "DISHPUTE_HOUSEHOLD_ID": os.environ.get("DISHPUTE_HOUSEHOLD_ID"),
            "DISHPUTE_USER_ID": os.environ.get("DISHPUTE_USER_ID"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing MCP configuration: {', '.join(missing)}")
        return cls(
            base_url=os.environ.get("DISHPUTE_API_URL", "http://127.0.0.1:8000"),
            household_id=UUID(required["DISHPUTE_HOUSEHOLD_ID"] or ""),
            user_id=UUID(required["DISHPUTE_USER_ID"] or ""),
            timezone_name=os.environ.get("DISHPUTE_TIMEZONE", "UTC"),
        )

    def local_datetime(self, work_date: date, work_time: time) -> datetime:
        return datetime.combine(work_date, work_time, self.timezone)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        write: bool = False,
    ) -> Any:
        headers = {"X-Actor-User-Id": str(self.user_id)}
        if write:
            headers["Idempotency-Key"] = str(uuid4())
        async with httpx.AsyncClient(
            base_url=self.base_url,
            transport=self.transport,
            timeout=15,
        ) as client:
            response = await client.request(method, path, headers=headers, json=json, params=params)
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise DishputeApiError(f"Dishpute returned {response.status_code}: {detail}")
        return response.json()


def build_mcp(client: DishputeApiClient) -> FastMCP:
    server = FastMCP(
        "Dishpute",
        instructions=(
            "Manage shared household planning and completed work. Past work should use "
            "record_work. Future work should use create_task, followed by schedule_task "
            "when a time is known. 'I' means the authenticated Dishpute member. Personal "
            "work remains visible to the household but normally does not count toward "
            "household fairness."
        ),
        stateless_http=True,
        json_response=True,
        host=os.environ.get("DISHPUTE_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("DISHPUTE_MCP_PORT", "8001")),
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    write_tool = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    @server.tool(annotations=write_tool, structured_output=True)
    async def record_work(
        title: str,
        work_date: date,
        start_time: time,
        end_time: time,
        category: str = "other",
        work_scope: Literal["household", "personal"] = "household",
        counts_toward_fairness: bool | None = None,
        completed_by_user_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        """Record work that already happened. Use for phrases such as 'I just wrote a proposal 2pm-3pm'."""
        started_at = client.local_datetime(work_date, start_time)
        ended_at = client.local_datetime(work_date, end_time)
        if ended_at <= started_at:
            raise ValueError("end_time must be after start_time on the same date")
        return await client.request(
            "POST",
            f"/households/{client.household_id}/completed-work",
            write=True,
            json={
                "category": category,
                "description": title,
                "work_scope": work_scope,
                "counts_toward_fairness": counts_toward_fairness,
                "participant_user_ids": [
                    str(value) for value in (completed_by_user_ids or [client.user_id])
                ],
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )

    @server.tool(annotations=write_tool, structured_output=True)
    async def create_task(
        title: str,
        description: str | None = None,
        category: str = "other",
        work_scope: Literal["household", "personal"] = "household",
        participant_user_ids: list[UUID] | None = None,
        parent_task_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Create future or unscheduled work. Do not use this for unmatched work that already happened."""
        return await client.request(
            "POST",
            f"/households/{client.household_id}/tasks",
            write=True,
            json={
                "title": title,
                "description": description,
                "category": category,
                "work_scope": work_scope,
                "participant_user_ids": [str(value) for value in (participant_user_ids or [])],
                "parent_task_id": str(parent_task_id) if parent_task_id else None,
            },
        )

    @server.tool(annotations=read_only, structured_output=True)
    async def list_work_items() -> list[dict[str, Any]]:
        """List shared Tasks and completed work visible in the Dishpute Tasks tab."""
        return await client.request("GET", f"/households/{client.household_id}/work-items")

    @server.tool(annotations=read_only, structured_output=True)
    async def get_calendar(range_start: date, range_end: date) -> list[dict[str, Any]]:
        """Read planned and completed Calendar items from range_start through the day before range_end."""
        starts_at = client.local_datetime(range_start, time.min)
        ends_at = client.local_datetime(range_end, time.min)
        if ends_at <= starts_at:
            raise ValueError("range_end must be after range_start")
        return await client.request(
            "GET",
            f"/households/{client.household_id}/calendar-items",
            params={
                "range_start": starts_at.isoformat(),
                "range_end": ends_at.isoformat(),
            },
        )

    @server.tool(annotations=write_tool, structured_output=True)
    async def update_task(
        task_id: UUID,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        work_scope: Literal["household", "personal"] | None = None,
        participant_user_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        """Update a shared Task's details or participants without changing Household membership."""
        values = {
            "title": title,
            "description": description,
            "category": category,
            "work_scope": work_scope,
            "participant_user_ids": (
                [str(value) for value in participant_user_ids]
                if participant_user_ids is not None
                else None
            ),
        }
        payload = {name: value for name, value in values.items() if value is not None}
        if not payload:
            raise ValueError("Provide at least one Task field to update")
        return await client.request(
            "PATCH",
            f"/households/{client.household_id}/tasks/{task_id}",
            write=True,
            json=payload,
        )

    @server.tool(annotations=write_tool, structured_output=True)
    async def schedule_task(
        task_id: UUID,
        work_date: date,
        start_time: time,
        end_time: time,
        participant_user_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        """Reserve a planned Time Block for an existing Task."""
        starts_at = client.local_datetime(work_date, start_time)
        ends_at = client.local_datetime(work_date, end_time)
        return await client.request(
            "POST",
            f"/households/{client.household_id}/tasks/{task_id}/time-blocks",
            write=True,
            json={
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "participant_user_ids": (
                    [str(value) for value in participant_user_ids]
                    if participant_user_ids is not None
                    else None
                ),
            },
        )

    @server.tool(annotations=write_tool, structured_output=True)
    async def reschedule_time_block(
        time_block_id: UUID,
        work_date: date,
        start_time: time,
        end_time: time,
    ) -> dict[str, Any]:
        """Move an existing planned Time Block without deleting its Task."""
        return await client.request(
            "PATCH",
            f"/households/{client.household_id}/time-blocks/{time_block_id}",
            write=True,
            json={
                "starts_at": client.local_datetime(work_date, start_time).isoformat(),
                "ends_at": client.local_datetime(work_date, end_time).isoformat(),
            },
        )

    @server.tool(annotations=write_tool, structured_output=True)
    async def complete_task(task_id: UUID) -> dict[str, Any]:
        """Explicitly mark a Task completed. This does not create completed-work duration by itself."""
        return await client.request(
            "PATCH",
            f"/households/{client.household_id}/tasks/{task_id}/lifecycle",
            write=True,
            json={"lifecycle_status": "completed"},
        )

    return server


def main() -> None:
    build_mcp(DishputeApiClient.from_environment()).run(transport="streamable-http")


if __name__ == "__main__":
    main()

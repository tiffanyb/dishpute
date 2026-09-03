import os
from datetime import date, datetime, time
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from dishpute.auth import AuthenticationError
from dishpute.database import build_engine, build_session_factory
from dishpute.oauth_provider import DishputeOAuthProvider


class DishputeApiError(RuntimeError):
    pass


class DishputeApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        household_id: UUID | None,
        user_id: UUID | None,
        timezone_name: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.household_id = household_id
        self.user_id = user_id
        self.default_timezone = ZoneInfo(timezone_name)
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
        access_token = get_access_token()
        timezone_name = (access_token.claims or {}).get("timezone") if access_token else None
        return datetime.combine(work_date, work_time, ZoneInfo(timezone_name) if timezone_name else self.default_timezone)

    @property
    def active_household_id(self) -> UUID:
        access_token = get_access_token()
        value = (access_token.claims or {}).get("household_id") if access_token else None
        if value:
            return UUID(value)
        if self.household_id is None:
            raise RuntimeError("The OAuth token does not identify a household")
        return self.household_id

    @property
    def active_user_id(self) -> UUID:
        access_token = get_access_token()
        if access_token and access_token.subject:
            return UUID(access_token.subject)
        if self.user_id is None:
            raise RuntimeError("The OAuth token does not identify a member")
        return self.user_id

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        write: bool = False,
    ) -> Any:
        access_token = get_access_token()
        headers = (
            {"Authorization": f"Bearer {access_token.token}"}
            if access_token
            else {"X-Actor-User-Id": str(self.active_user_id)}
        )
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
        if response.status_code == 204:
            return {}
        return response.json()


def build_mcp(
    client: DishputeApiClient,
    *,
    oauth_provider: DishputeOAuthProvider | None = None,
    auth_settings: AuthSettings | None = None,
    transport_security: TransportSecuritySettings | None = None,
) -> FastMCP:
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
        auth_server_provider=oauth_provider,
        auth=auth_settings,
        transport_security=transport_security,
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
    destructive_tool = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
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
            f"/households/{client.active_household_id}/completed-work",
            write=True,
            json={
                "category": category,
                "description": title,
                "work_scope": work_scope,
                "counts_toward_fairness": counts_toward_fairness,
                "participant_user_ids": [
                    str(value) for value in (completed_by_user_ids or [client.active_user_id])
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
            f"/households/{client.active_household_id}/tasks",
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
        return await client.request("GET", f"/households/{client.active_household_id}/work-items")

    @server.tool(annotations=read_only, structured_output=True)
    async def get_calendar(range_start: date, range_end: date) -> list[dict[str, Any]]:
        """Read planned and completed Calendar items from range_start through the day before range_end."""
        starts_at = client.local_datetime(range_start, time.min)
        ends_at = client.local_datetime(range_end, time.min)
        if ends_at <= starts_at:
            raise ValueError("range_end must be after range_start")
        return await client.request(
            "GET",
            f"/households/{client.active_household_id}/calendar-items",
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
            f"/households/{client.active_household_id}/tasks/{task_id}",
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
            f"/households/{client.active_household_id}/tasks/{task_id}/time-blocks",
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
            f"/households/{client.active_household_id}/time-blocks/{time_block_id}",
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
            f"/households/{client.active_household_id}/tasks/{task_id}/lifecycle",
            write=True,
            json={"lifecycle_status": "completed"},
        )

    @server.tool(annotations=destructive_tool, structured_output=True)
    async def delete_task(task_id: UUID) -> dict[str, Any]:
        """Permanently delete a Task created by the authenticated member."""
        await client.request(
            "DELETE",
            f"/households/{client.active_household_id}/tasks/{task_id}",
            write=True,
        )
        return {"deleted": True, "task_id": str(task_id)}

    return server


def build_oauth_mcp() -> FastMCP:
    issuer_url = os.environ["DISHPUTE_MCP_PUBLIC_URL"].rstrip("/")
    issuer = AnyHttpUrl(issuer_url)
    database_url = os.environ["DATABASE_URL"]
    provider = DishputeOAuthProvider(
        build_session_factory(build_engine(database_url)),
        issuer_url,
    )
    auth_settings = AuthSettings(
        issuer_url=issuer,
        resource_server_url=AnyHttpUrl(f"{issuer_url}/mcp"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["dishpute:read", "dishpute:write"],
            default_scopes=["dishpute:read", "dishpute:write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=["dishpute:read", "dishpute:write"],
    )
    client = DishputeApiClient(
        base_url=os.environ.get("DISHPUTE_API_URL", "http://127.0.0.1:8000"),
        household_id=None,
        user_id=None,
        timezone_name="UTC",
    )
    host_with_port = urlparse(issuer_url).netloc
    server = build_mcp(
        client,
        oauth_provider=provider,
        auth_settings=auth_settings,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host_with_port, "127.0.0.1:8001", "localhost:8001"],
            allowed_origins=[issuer_url],
        ),
    )

    def authorization_server_metadata() -> dict[str, Any]:
        return {
            "issuer": f"{issuer_url}/",
            "authorization_endpoint": f"{issuer_url}/authorize",
            "token_endpoint": f"{issuer_url}/token",
            "registration_endpoint": f"{issuer_url}/register",
            "scopes_supported": ["dishpute:read", "dishpute:write"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
                "none",
            ],
            "revocation_endpoint": f"{issuer_url}/revoke",
            "revocation_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
                "none",
            ],
            "code_challenge_methods_supported": ["S256"],
        }

    def protected_resource_metadata() -> dict[str, Any]:
        return {
            "resource": f"{issuer_url}/mcp",
            "authorization_servers": [f"{issuer_url}/"],
            "scopes_supported": ["dishpute:read", "dishpute:write"],
            "bearer_methods_supported": ["header"],
        }

    def metadata_headers() -> dict[str, str]:
        return {
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": (
                "Accept, Accept-Language, Content-Language, Content-Type, "
                "MCP-Protocol-Version"
            ),
            "Access-Control-Max-Age": "600",
        }

    def metadata_options_response() -> Response:
        return Response("OK", headers=metadata_headers())

    @server.custom_route("/.well-known/oauth-protected-resource", methods=["GET", "OPTIONS"])
    @server.custom_route("/mcp/.well-known/oauth-protected-resource", methods=["GET", "OPTIONS"])
    async def oauth_protected_resource_metadata(_request: Request):
        if _request.method == "OPTIONS":
            return metadata_options_response()
        return JSONResponse(
            protected_resource_metadata(),
            headers=metadata_headers(),
        )

    @server.custom_route("/.well-known/oauth-authorization-server/mcp", methods=["GET", "OPTIONS"])
    @server.custom_route("/.well-known/oauth-authorization-server/mcp/", methods=["GET", "OPTIONS"])
    @server.custom_route("/mcp/.well-known/oauth-authorization-server", methods=["GET", "OPTIONS"])
    @server.custom_route("/mcp/.well-known/oauth-authorization-server/", methods=["GET", "OPTIONS"])
    @server.custom_route("/.well-known/openid-configuration", methods=["GET", "OPTIONS"])
    @server.custom_route("/.well-known/openid-configuration/", methods=["GET", "OPTIONS"])
    @server.custom_route("/mcp/.well-known/openid-configuration", methods=["GET", "OPTIONS"])
    @server.custom_route("/mcp/.well-known/openid-configuration/", methods=["GET", "OPTIONS"])
    async def oauth_authorization_server_metadata(_request: Request):
        if _request.method == "OPTIONS":
            return metadata_options_response()
        return JSONResponse(
            authorization_server_metadata(),
            headers=metadata_headers(),
        )

    @server.custom_route("/.well-known/oauth-authorization-server/", methods=["GET", "OPTIONS"])
    async def oauth_authorization_server_metadata_trailing_slash(_request: Request):
        if _request.method == "OPTIONS":
            return metadata_options_response()
        return JSONResponse(
            authorization_server_metadata(),
            headers=metadata_headers(),
        )

    @server.custom_route("/oauth/login", methods=["GET", "POST"])
    async def oauth_login(request: Request):
        if request.method == "GET":
            request_token = request.query_params.get("request", "")
            page = provider.authorization_page(request_token)
            if page is None:
                return HTMLResponse("Connection request expired", status_code=400)
            return HTMLResponse(page)

        form = await request.form()
        request_token = str(form.get("request", ""))
        try:
            redirect_url = provider.complete_authorization(
                request_token,
                str(form.get("email", "")),
                str(form.get("password", "")),
            )
        except AuthenticationError as exc:
            page = provider.authorization_page(request_token, str(exc))
            return HTMLResponse(page or "Connection request expired", status_code=401)
        return RedirectResponse(redirect_url, status_code=303)

    return server


def main() -> None:
    if os.environ.get("DISHPUTE_MCP_PUBLIC_URL"):
        build_oauth_mcp().run(transport="streamable-http")
    else:
        build_mcp(DishputeApiClient.from_environment()).run(transport="streamable-http")


if __name__ == "__main__":
    main()

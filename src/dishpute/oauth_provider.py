from __future__ import annotations

import html
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse
from uuid import UUID

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dishpute.auth import AuthenticationError, authenticate_password, digest_secret
from dishpute.models import (
    AuthSession,
    Household,
    HouseholdMembership,
    OAuthAccessGrant,
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthRefreshGrant,
)

AUTHORIZATION_REQUEST_LIFETIME = timedelta(minutes=10)
AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=5)
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)


class DishputeAuthorizationCode(AuthorizationCode):
    household_id: UUID


class DishputeRefreshToken(RefreshToken):
    household_id: UUID


class DishputeOAuthProvider:
    def __init__(self, session_factory: sessionmaker[Session], issuer_url: str) -> None:
        self.session_factory = session_factory
        self.issuer_url = issuer_url.rstrip("/")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self.session_factory() as session:
            record = session.get(OAuthClient, client_id)
            if record is None:
                return None
            values = dict(record.metadata_json)
            values["client_secret"] = record.client_secret
            return OAuthClientInformationFull.model_validate(values)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError("invalid_client_metadata", "client_id is required")
        for redirect_uri in client_info.redirect_uris or []:
            parsed = urlparse(str(redirect_uri))
            is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
                raise RegistrationError(
                    "invalid_redirect_uri", "redirect URIs must use HTTPS or HTTP loopback"
                )
        with self.session_factory.begin() as session:
            if session.get(OAuthClient, client_info.client_id) is not None:
                raise RegistrationError("invalid_client_metadata", "client_id already exists")
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_secret=client_info.client_secret,
                    metadata_json=client_info.model_dump(mode="json", exclude={"client_secret"}),
                )
            )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if not client.client_id:
            raise AuthorizeError("invalid_request", "client_id is required")
        request_token = secrets.token_urlsafe(32)
        with self.session_factory.begin() as session:
            session.add(
                OAuthAuthorizationRequest(
                    request_token_hash=digest_secret(request_token),
                    client_id=client.client_id,
                    params_json=params.model_dump(mode="json"),
                    expires_at=datetime.now(UTC) + AUTHORIZATION_REQUEST_LIFETIME,
                )
            )
        return f"{self.issuer_url}/oauth/login?{urlencode({'request': request_token})}"

    def authorization_page(self, request_token: str, error: str | None = None) -> str | None:
        with self.session_factory() as session:
            pending = session.get(OAuthAuthorizationRequest, digest_secret(request_token))
            if pending is None or pending.expires_at <= datetime.now(UTC):
                return None
            client = session.get(OAuthClient, pending.client_id)
            client_name = (client.metadata_json.get("client_name") if client else None) or "an MCP client"
        message = f'<p class="error">{html.escape(error)}</p>' if error else ""
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Connect Dishpute</title><style>
body{{font:16px system-ui;margin:0;background:#f4f6f5;color:#17201c}}main{{max-width:420px;margin:10vh auto;padding:28px}}
form{{background:white;border:1px solid #ccd5d0;padding:24px}}label{{display:block;margin:16px 0 6px}}
input{{box-sizing:border-box;width:100%;padding:10px;border:1px solid #8b9991}}button{{margin-top:20px;padding:10px 16px;background:#176b4d;color:white;border:0}}
.error{{color:#a12626}}small{{color:#526159}}
</style></head><body><main><h1>Connect Dishpute</h1>
<p><strong>{html.escape(str(client_name))}</strong> is requesting access to manage your shared household work.</p>
{message}<form method="post" action="/oauth/login"><input type="hidden" name="request" value="{html.escape(request_token)}">
<label for="email">Email</label><input id="email" name="email" type="email" required autocomplete="username">
<label for="password">Password</label><input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">Connect</button></form><p><small>Your password is verified by Dishpute and is never sent to the MCP client.</small></p>
</main></body></html>"""

    def complete_authorization(self, request_token: str, email: str, password: str) -> str:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            pending = session.get(OAuthAuthorizationRequest, digest_secret(request_token))
            if pending is None or pending.expires_at <= now:
                raise AuthenticationError("This connection request has expired")
            user_id = authenticate_password(session, email, password)
            memberships = session.scalars(
                select(HouseholdMembership).where(
                    HouseholdMembership.user_id == user_id,
                    HouseholdMembership.status == "active",
                )
            ).all()
            if len(memberships) != 1:
                raise AuthenticationError(
                    "Your account must belong to exactly one active household to connect"
                )
            params = AuthorizationParams.model_validate(pending.params_json)
            code = secrets.token_urlsafe(32)
            session.add(
                OAuthAuthorizationCode(
                    code_hash=digest_secret(code),
                    client_id=pending.client_id,
                    user_id=user_id,
                    household_id=memberships[0].household_id,
                    params_json=params.model_dump(mode="json"),
                    expires_at=now + AUTHORIZATION_CODE_LIFETIME,
                )
            )
            session.delete(pending)
        query = {"code": code}
        if params.state:
            query["state"] = params.state
        separator = "&" if "?" in str(params.redirect_uri) else "?"
        return f"{params.redirect_uri}{separator}{urlencode(query)}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> DishputeAuthorizationCode | None:
        with self.session_factory() as session:
            record = session.get(OAuthAuthorizationCode, digest_secret(authorization_code))
            if record is None or record.used_at is not None or record.client_id != client.client_id:
                return None
            params = AuthorizationParams.model_validate(record.params_json)
            return DishputeAuthorizationCode(
                code=authorization_code,
                scopes=params.scopes or [],
                expires_at=record.expires_at.timestamp(),
                client_id=record.client_id,
                code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource,
                subject=str(record.user_id),
                household_id=record.household_id,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: DishputeAuthorizationCode
    ) -> OAuthToken:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            record = session.get(OAuthAuthorizationCode, digest_secret(authorization_code.code))
            if record is None or record.used_at is not None or record.expires_at <= now:
                raise TokenError("invalid_grant", "authorization code is invalid or expired")
            record.used_at = now
            return self._issue_tokens(
                session,
                client_id=record.client_id,
                user_id=record.user_id,
                household_id=record.household_id,
                scopes=authorization_code.scopes,
            )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> DishputeRefreshToken | None:
        with self.session_factory() as session:
            record = session.get(OAuthRefreshGrant, digest_secret(refresh_token))
            if (
                record is None
                or record.client_id != client.client_id
                or record.revoked_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                return None
            return DishputeRefreshToken(
                token=refresh_token,
                client_id=record.client_id,
                scopes=record.scopes,
                expires_at=int(record.expires_at.timestamp()),
                subject=str(record.user_id),
                household_id=record.household_id,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: DishputeRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        with self.session_factory.begin() as session:
            record = session.get(OAuthRefreshGrant, digest_secret(refresh_token.token))
            if record is None or record.revoked_at is not None:
                raise TokenError("invalid_grant", "refresh token is invalid")
            record.revoked_at = datetime.now(UTC)
            return self._issue_tokens(
                session,
                client_id=record.client_id,
                user_id=record.user_id,
                household_id=record.household_id,
                scopes=scopes,
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        now = datetime.now(UTC)
        token_hash = digest_secret(token)
        with self.session_factory() as session:
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash)
            )
            grant = session.get(OAuthAccessGrant, token_hash)
            if (
                auth_session is None
                or grant is None
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
            ):
                return None
            household = session.get(Household, grant.household_id)
            if household is None:
                return None
            return AccessToken(
                token=token,
                client_id=grant.client_id,
                scopes=grant.scopes,
                expires_at=int(auth_session.expires_at.timestamp()),
                subject=str(auth_session.user_id),
                claims={
                    "household_id": str(grant.household_id),
                    "timezone": household.default_timezone,
                },
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        now = datetime.now(UTC)
        token_hash = digest_secret(token.token)
        with self.session_factory.begin() as session:
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_hash)
            )
            refresh = session.get(OAuthRefreshGrant, token_hash)
            if auth_session is not None:
                auth_session.revoked_at = now
            if refresh is not None:
                refresh.revoked_at = now

    def _issue_tokens(
        self,
        session: Session,
        *,
        client_id: str,
        user_id: UUID,
        household_id: UUID,
        scopes: list[str],
    ) -> OAuthToken:
        now = datetime.now(UTC)
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(48)
        access_hash = digest_secret(access_token)
        session.add(
            AuthSession(
                user_id=user_id,
                token_hash=access_hash,
                expires_at=now + ACCESS_TOKEN_LIFETIME,
            )
        )
        session.add(
            OAuthAccessGrant(
                token_hash=access_hash,
                client_id=client_id,
                household_id=household_id,
                scopes=scopes,
            )
        )
        session.add(
            OAuthRefreshGrant(
                token_hash=digest_secret(refresh_token),
                client_id=client_id,
                user_id=user_id,
                household_id=household_id,
                scopes=scopes,
                expires_at=now + REFRESH_TOKEN_LIFETIME,
            )
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

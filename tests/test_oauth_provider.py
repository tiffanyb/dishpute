import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy.orm import sessionmaker

from dishpute.oauth_provider import DishputeOAuthProvider


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


@pytest.mark.anyio
async def test_oauth_authorization_tokens_and_rotation(api_client, session) -> None:
    account = api_client.post(
        "/auth/signup",
        json={
            "display_name": "Tiffany",
            "email": "tiffany@example.com",
            "password": "correct horse battery staple",
        },
    ).json()
    household = api_client.post(
        "/households",
        headers={"Authorization": f"Bearer {account['access_token']}"},
        json={"name": "Bao household", "default_timezone": "America/Phoenix"},
    ).json()
    factory = sessionmaker(
        bind=session.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    provider = DishputeOAuthProvider(factory, "https://mcp.example.test")
    client = OAuthClientInformationFull(
        client_id="claude-client",
        client_secret=None,
        redirect_uris=[AnyUrl("https://claude.example.test/callback")],
        token_endpoint_auth_method="none",
        scope="dishpute:read dishpute:write",
    )
    await provider.register_client(client)
    loaded_client = await provider.get_client("claude-client")
    assert loaded_client is not None

    verifier = "a" * 48
    params = AuthorizationParams(
        state="client-state",
        scopes=["dishpute:read", "dishpute:write"],
        code_challenge=_pkce_challenge(verifier),
        redirect_uri=AnyUrl("https://claude.example.test/callback"),
        redirect_uri_provided_explicitly=True,
        resource="https://mcp.example.test/mcp",
    )
    login_url = await provider.authorize(client, params)
    request_token = parse_qs(urlparse(login_url).query)["request"][0]
    assert provider.authorization_page(request_token) is not None

    callback = provider.complete_authorization(
        request_token, "tiffany@example.com", "correct horse battery staple"
    )
    callback_values = parse_qs(urlparse(callback).query)
    assert callback_values["state"] == ["client-state"]
    code = callback_values["code"][0]
    authorization_code = await provider.load_authorization_code(client, code)
    assert authorization_code is not None
    assert authorization_code.subject == account["user_id"]
    assert str(authorization_code.household_id) == household["id"]

    tokens = await provider.exchange_authorization_code(client, authorization_code)
    access = await provider.load_access_token(tokens.access_token)
    assert access is not None
    assert access.subject == account["user_id"]
    assert access.claims == {"household_id": household["id"]}

    me = api_client.get("/me", headers={"Authorization": f"Bearer {tokens.access_token}"})
    assert me.status_code == 200
    assert me.json()["user_id"] == account["user_id"]

    refresh = await provider.load_refresh_token(client, tokens.refresh_token or "")
    assert refresh is not None
    rotated = await provider.exchange_refresh_token(client, refresh, refresh.scopes)
    assert await provider.load_refresh_token(client, tokens.refresh_token or "") is None
    assert await provider.load_access_token(rotated.access_token) is not None

    rotated_access = await provider.load_access_token(rotated.access_token)
    assert rotated_access is not None
    await provider.revoke_token(rotated_access)
    assert await provider.load_access_token(rotated.access_token) is None


@pytest.mark.anyio
async def test_oauth_rejects_non_https_redirect(session) -> None:
    factory = sessionmaker(
        bind=session.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    provider = DishputeOAuthProvider(factory, "https://mcp.example.test")
    client = OAuthClientInformationFull(
        client_id="unsafe-client",
        redirect_uris=[AnyUrl("http://elsewhere.example.test/callback")],
        token_endpoint_auth_method="none",
    )
    with pytest.raises(Exception, match="HTTPS"):
        await provider.register_client(client)

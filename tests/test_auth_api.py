from sqlalchemy import select
from sqlalchemy.orm import Session

from dishpute.models import AuthSession, HouseholdInvite, PasswordCredential


def signup(client, name: str, email: str) -> dict:
    response = client.post(
        "/auth/signup",
        json={"display_name": name, "email": email, "password": "long-test-password"},
    )
    assert response.status_code == 201
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_members_can_create_and_join_a_household(api_client, session: Session) -> None:
    tiffany = signup(api_client, "Tiffany", "TIFFANY@example.com")
    husband = signup(api_client, "Husband", "husband@example.com")

    created = api_client.post(
        "/households",
        headers=bearer(tiffany["access_token"]),
        json={"name": "Our Home", "default_timezone": "America/Phoenix"},
    )
    assert created.status_code == 201
    household = created.json()
    assert session.in_transaction() is False

    invitation = api_client.post(
        f"/households/{household['id']}/invites",
        headers=bearer(tiffany["access_token"]),
    )
    assert invitation.status_code == 200

    joined = api_client.post(
        "/households/join",
        headers=bearer(husband["access_token"]),
        json={"invite_code": invitation.json()["invite_code"]},
    )
    assert joined.status_code == 200
    assert joined.json() == household

    members = api_client.get(
        f"/households/{household['id']}/members",
        headers=bearer(husband["access_token"]),
    )
    assert {member["display_name"] for member in members.json()} == {"Tiffany", "Husband"}

    credential = session.scalar(
        select(PasswordCredential).where(PasswordCredential.email == "tiffany@example.com")
    )
    assert credential is not None
    assert "long-test-password" not in credential.password_hash
    stored_session = session.scalar(
        select(AuthSession).where(AuthSession.user_id == tiffany["user_id"])
    )
    assert stored_session is not None
    assert stored_session.token_hash != tiffany["access_token"]
    stored_invite = session.scalar(select(HouseholdInvite))
    assert stored_invite is not None
    assert stored_invite.code_hash != invitation.json()["invite_code"]


def test_login_and_authentication_fail_safely(api_client) -> None:
    account = signup(api_client, "Tiffany", "tiffany@example.com")

    duplicate = api_client.post(
        "/auth/signup",
        json={
            "display_name": "Someone Else",
            "email": "tiffany@example.com",
            "password": "another-long-password",
        },
    )
    assert duplicate.status_code == 409

    bad_login = api_client.post(
        "/auth/login",
        json={"email": "tiffany@example.com", "password": "incorrect"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid email or password"

    login = api_client.post(
        "/auth/login",
        json={"email": "tiffany@example.com", "password": "long-test-password"},
    )
    assert login.status_code == 200
    assert login.json()["user_id"] == account["user_id"]

    unauthenticated = api_client.get("/me")
    assert unauthenticated.status_code == 401
    malformed = api_client.get("/me", headers={"Authorization": "Token no"})
    assert malformed.status_code == 401


def test_invite_is_single_use(api_client) -> None:
    owner = signup(api_client, "Owner", "owner@example.com")
    first_guest = signup(api_client, "First", "first@example.com")
    second_guest = signup(api_client, "Second", "second@example.com")
    household = api_client.post(
        "/households",
        headers=bearer(owner["access_token"]),
        json={"name": "Home"},
    ).json()
    code = api_client.post(
        f"/households/{household['id']}/invites", headers=bearer(owner["access_token"])
    ).json()["invite_code"]

    assert (
        api_client.post(
            "/households/join",
            headers=bearer(first_guest["access_token"]),
            json={"invite_code": code},
        ).status_code
        == 200
    )
    reused = api_client.post(
        "/households/join",
        headers=bearer(second_guest["access_token"]),
        json={"invite_code": code},
    )
    assert reused.status_code == 404

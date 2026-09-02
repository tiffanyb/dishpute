import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from dishpute.models import AuthSession, PasswordCredential

password_hash = PasswordHash.recommended()
SESSION_LIFETIME = timedelta(days=30)


class AuthenticationError(RuntimeError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(session: Session, user_id: UUID) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    record = AuthSession(
        user_id=user_id,
        token_hash=digest_secret(token),
        expires_at=datetime.now(UTC) + SESSION_LIFETIME,
    )
    session.add(record)
    session.flush()
    return token, record


def authenticate_password(session: Session, email: str, password: str) -> UUID:
    credential = session.scalar(
        select(PasswordCredential).where(PasswordCredential.email == normalize_email(email))
    )
    if credential is None or not password_hash.verify(password, credential.password_hash):
        raise AuthenticationError("Invalid email or password")
    return credential.user_id


def resolve_bearer_token(session: Session, authorization: str | None) -> UUID | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Use a Bearer session token")
    record = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == digest_secret(token))
    )
    if record is None or record.revoked_at is not None or record.expires_at <= datetime.now(UTC):
        raise AuthenticationError("Session is invalid or expired")
    return record.user_id


def development_headers_enabled() -> bool:
    return os.environ.get("DISHPUTE_ALLOW_DEV_ACTOR_HEADER", "true").lower() == "true"

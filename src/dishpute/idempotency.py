import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from dishpute.models import IntegrationRequest
from dishpute.services import ConflictError

CLIENT_NAME = "dishpute-application-api"


def _request_hash(operation: str, payload: BaseModel) -> str:
    canonical_request = json.dumps(
        {"operation": operation, "payload": payload.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_request.encode()).hexdigest()


def execute_idempotent[ResponseModel: BaseModel](
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    idempotency_key: str,
    operation: str,
    payload: BaseModel,
    response_model: type[ResponseModel],
    action: Callable[[], ResponseModel],
    response_status: int = 201,
) -> tuple[ResponseModel, bool]:
    normalized_key = idempotency_key.strip()
    request_hash = _request_hash(operation, payload)
    lock_key = f"{actor_user_id}:{CLIENT_NAME}:{normalized_key}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )

    existing = session.scalar(
        select(IntegrationRequest).where(
            IntegrationRequest.actor_user_id == actor_user_id,
            IntegrationRequest.client_name == CLIENT_NAME,
            IntegrationRequest.idempotency_key == normalized_key,
        )
    )
    if existing is not None:
        if (
            existing.household_id != household_id
            or existing.operation != operation
            or existing.request_hash != request_hash
        ):
            raise ConflictError("This Idempotency-Key was already used for a different request")
        if existing.response_body is None or existing.response_status is None:
            raise ConflictError("The original request has not finished")
        return response_model.model_validate(existing.response_body), True

    response = action()
    session.add(
        IntegrationRequest(
            household_id=household_id,
            actor_user_id=actor_user_id,
            client_name=CLIENT_NAME,
            idempotency_key=normalized_key,
            operation=operation,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response.model_dump(mode="json"),
            completed_at=datetime.now(UTC),
        )
    )
    session.flush()
    return response, False

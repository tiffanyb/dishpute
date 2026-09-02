import os
from collections.abc import Iterator
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from dishpute.database import build_engine, build_session_factory
from dishpute.idempotency import execute_idempotent
from dishpute.models import Household
from dishpute.natural_language import NaturalLanguageError, interpret
from dishpute.schemas import (
    CompletedWorkCreate,
    CompletedWorkResponse,
    ContributionResponse,
    NaturalLanguageCreate,
    NaturalLanguageResponse,
    TaskCreate,
    TaskResponse,
)
from dishpute.services import (
    ApplicationError,
    create_task,
    list_contributions,
    record_completed_work,
)


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://dishpute:dishpute-local-only@127.0.0.1:5432/dishpute",
)
engine = build_engine(DATABASE_URL)
SessionFactory = build_session_factory(engine)


def get_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


ActorUserId = Annotated[UUID, Header(alias="X-Actor-User-Id")]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
]
DatabaseSession = Annotated[Session, Depends(get_session)]


app = FastAPI(title="Dishpute API", version="0.1.0")


@app.exception_handler(ApplicationError)
def handle_application_error(_request: Request, error: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.exception_handler(NaturalLanguageError)
def handle_natural_language_error(
    _request: Request, error: NaturalLanguageError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/households/{household_id}/natural-language",
    response_model=NaturalLanguageResponse,
    status_code=status.HTTP_201_CREATED,
)
def natural_language_route(
    household_id: UUID,
    payload: NaturalLanguageCreate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> NaturalLanguageResponse:
    with session.begin():
        household = session.get(Household, household_id)
        if household is None:
            raise ApplicationError("Household was not found")

        def perform_action() -> NaturalLanguageResponse:
            command = interpret(
                payload.text,
                reference_date=payload.reference_date,
                timezone_name=household.default_timezone,
            )
            if command.action == "record_completed_work":
                result = record_completed_work(
                    session,
                    household_id=household_id,
                    actor_user_id=actor_user_id,
                    category=command.category,
                    description=command.title,
                    participant_user_ids=[actor_user_id],
                    started_at=command.started_at,
                    ended_at=command.ended_at,
                    duration_override_minutes=None,
                )
                completed_work = CompletedWorkResponse(
                    completion_record_id=result.completion.id,
                    time_block_id=(
                        result.time_block.id if result.time_block is not None else None
                    ),
                    task_id=result.completion.task_id,
                    participant_user_ids=result.participant_user_ids,
                    effective_duration_minutes=result.effective_duration_minutes,
                )
                return NaturalLanguageResponse(
                    interpreted_action=command.action,
                    completed_work=completed_work,
                )

            result = create_task(
                session,
                household_id=household_id,
                actor_user_id=actor_user_id,
                title=command.title,
                category=command.category,
                participant_user_ids=(
                    [actor_user_id] if command.started_at is not None else []
                ),
                parent_task_id=payload.parent_task_id,
                scheduled_start=command.started_at,
                scheduled_end=command.ended_at,
            )
            task = TaskResponse(
                id=result.task.id,
                household_id=result.task.household_id,
                title=result.task.title,
                description=result.task.description,
                category=result.task.category,
                lifecycle_status=result.task.lifecycle_status,
                parent_task_id=result.task.parent_task_id,
                participant_user_ids=result.participant_user_ids,
                time_block_id=(
                    result.time_block.id if result.time_block is not None else None
                ),
            )
            return NaturalLanguageResponse(interpreted_action=command.action, task=task)

        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation="interpret_natural_language",
            payload=payload,
            response_model=NaturalLanguageResponse,
            action=perform_action,
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.post(
    "/households/{household_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_route(
    household_id: UUID,
    payload: TaskCreate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> TaskResponse:
    with session.begin():
        def perform_action() -> TaskResponse:
            created = create_task(
                session,
                household_id=household_id,
                actor_user_id=actor_user_id,
                **payload.model_dump(),
            )
            return TaskResponse(
                id=created.task.id,
                household_id=created.task.household_id,
                title=created.task.title,
                description=created.task.description,
                category=created.task.category,
                lifecycle_status=created.task.lifecycle_status,
                parent_task_id=created.task.parent_task_id,
                participant_user_ids=created.participant_user_ids,
                time_block_id=(
                    created.time_block.id if created.time_block is not None else None
                ),
            )

        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation="create_task",
            payload=payload,
            response_model=TaskResponse,
            action=perform_action,
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.post(
    "/households/{household_id}/completed-work",
    response_model=CompletedWorkResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_completed_work_route(
    household_id: UUID,
    payload: CompletedWorkCreate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> CompletedWorkResponse:
    with session.begin():
        def perform_action() -> CompletedWorkResponse:
            recorded = record_completed_work(
                session,
                household_id=household_id,
                actor_user_id=actor_user_id,
                **payload.model_dump(),
            )
            return CompletedWorkResponse(
                completion_record_id=recorded.completion.id,
                time_block_id=(
                    recorded.time_block.id if recorded.time_block is not None else None
                ),
                task_id=recorded.completion.task_id,
                participant_user_ids=recorded.participant_user_ids,
                effective_duration_minutes=recorded.effective_duration_minutes,
            )

        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation="record_completed_work",
            payload=payload,
            response_model=CompletedWorkResponse,
            action=perform_action,
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.get(
    "/households/{household_id}/contributions",
    response_model=list[ContributionResponse],
)
def list_contributions_route(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> list[ContributionResponse]:
    contributions = list_contributions(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        start_date=start_date,
        end_date=end_date,
    )
    return [ContributionResponse(**contribution.__dict__) for contribution in contributions]

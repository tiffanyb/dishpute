import os
from collections.abc import Iterator
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from dishpute.database import build_engine, build_session_factory
from dishpute.schemas import (
    CompletedWorkCreate,
    CompletedWorkResponse,
    ContributionResponse,
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
DatabaseSession = Annotated[Session, Depends(get_session)]


app = FastAPI(title="Dishpute API", version="0.1.0")


@app.exception_handler(ApplicationError)
def handle_application_error(_request: Request, error: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/households/{household_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_route(
    household_id: UUID,
    payload: TaskCreate,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> TaskResponse:
    with session.begin():
        result = create_task(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            **payload.model_dump(),
        )
    return TaskResponse(
        id=result.task.id,
        household_id=result.task.household_id,
        title=result.task.title,
        description=result.task.description,
        category=result.task.category,
        lifecycle_status=result.task.lifecycle_status,
        parent_task_id=result.task.parent_task_id,
        participant_user_ids=result.participant_user_ids,
        time_block_id=result.time_block.id if result.time_block is not None else None,
    )


@app.post(
    "/households/{household_id}/completed-work",
    response_model=CompletedWorkResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_completed_work_route(
    household_id: UUID,
    payload: CompletedWorkCreate,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> CompletedWorkResponse:
    with session.begin():
        result = record_completed_work(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            **payload.model_dump(),
        )
    return CompletedWorkResponse(
        completion_record_id=result.completion.id,
        time_block_id=result.time_block.id if result.time_block is not None else None,
        task_id=result.completion.task_id,
        participant_user_ids=result.participant_user_ids,
        effective_duration_minutes=result.effective_duration_minutes,
    )


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


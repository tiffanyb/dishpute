import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dishpute.auth import (
    AuthenticationError,
    authenticate_password,
    create_session,
    development_headers_enabled,
    digest_secret,
    normalize_email,
    password_hash,
    resolve_bearer_token,
)
from dishpute.database import build_engine, build_session_factory
from dishpute.idempotency import execute_idempotent
from dishpute.models import (
    AppUser,
    Household,
    HouseholdInvite,
    HouseholdMembership,
    PasswordCredential,
)
from dishpute.natural_language import NaturalLanguageError, interpret
from dishpute.schemas import (
    AuthResponse,
    CalendarItemResponse,
    CompletedWorkCreate,
    CompletedWorkResponse,
    ContributionResponse,
    HouseholdCreate,
    HouseholdMemberResponse,
    HouseholdResponse,
    InviteAccept,
    InviteResponse,
    LoginCreate,
    NaturalLanguageCreate,
    NaturalLanguageResponse,
    SignUpCreate,
    TaskCreate,
    TaskDetailResponse,
    TaskLifecycleUpdate,
    TaskResponse,
    TaskScheduleCreate,
    TaskSummary,
    TaskTimeBlockResponse,
    TaskUpdate,
    TimeBlockUpdate,
    WorkItemResponse,
)
from dishpute.services import (
    ApplicationError,
    CalendarItem,
    ListedTask,
    ListedTimeBlock,
    TaskDetails,
    create_task,
    delete_task,
    get_task_details,
    list_calendar_items,
    list_contributions,
    list_household_members,
    list_tasks,
    list_work_items,
    record_completed_work,
    schedule_task,
    update_planned_time_block,
    update_task,
    update_task_lifecycle,
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


IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]
DatabaseSession = Annotated[Session, Depends(get_session)]


def get_actor_user_id(
    session: DatabaseSession,
    authorization: Annotated[str | None, Header()] = None,
    development_actor_id: Annotated[UUID | None, Header(alias="X-Actor-User-Id")] = None,
) -> UUID:
    try:
        bearer_user_id = resolve_bearer_token(session, authorization)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    if bearer_user_id is not None:
        return bearer_user_id
    if development_actor_id is not None and development_headers_enabled():
        return development_actor_id
    raise HTTPException(status_code=401, detail="Authentication required")


ActorUserId = Annotated[UUID, Depends(get_actor_user_id)]


app = FastAPI(title="Dishpute API", version="0.1.0")
WEB_ROOT = Path(__file__).with_name("web")
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")


@contextmanager
def _transaction(session: Session):
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise


def _task_summary(result: ListedTask) -> TaskSummary:
    return TaskSummary(
        id=result.task.id,
        title=result.task.title,
        category=result.task.category,
        work_scope=result.task.work_scope,
        lifecycle_status=result.task.lifecycle_status,
        parent_task_id=result.task.parent_task_id,
        participant_user_ids=result.participant_user_ids,
        scheduled=result.scheduled,
    )


def _time_block_response(result: ListedTimeBlock) -> TaskTimeBlockResponse:
    return TaskTimeBlockResponse(
        id=result.time_block.id,
        title=result.time_block.title,
        starts_at=result.time_block.starts_at,
        ends_at=result.time_block.ends_at,
        status=result.time_block.status,
        work_scope=result.time_block.work_scope,
        participant_user_ids=result.participant_user_ids,
    )


def _calendar_item_response(result: CalendarItem) -> CalendarItemResponse:
    completion = result.completion
    return CalendarItemResponse(
        id=result.time_block.id,
        item_type="completed" if result.time_block.block_kind == "actual" else "planned",
        title=result.time_block.title,
        category=result.category,
        work_scope=result.time_block.work_scope,
        status=result.time_block.status,
        starts_at=result.time_block.starts_at,
        ends_at=result.time_block.ends_at,
        participant_user_ids=result.participant_user_ids,
        task_ids=result.task_ids,
        completion_record_id=completion.id if completion is not None else None,
        counts_toward_fairness=(
            completion.counts_toward_fairness if completion is not None else None
        ),
    )


def _task_detail(result: TaskDetails) -> TaskDetailResponse:
    return TaskDetailResponse(
        **_task_summary(
            ListedTask(
                task=result.task,
                participant_user_ids=result.participant_user_ids,
                scheduled=result.scheduled,
            )
        ).model_dump(),
        household_id=result.task.household_id,
        created_by_user_id=result.task.created_by_user_id,
        description=result.task.description,
        subtasks=[_task_summary(subtask) for subtask in result.subtasks],
        time_blocks=[_time_block_response(block) for block in result.time_blocks],
    )


@app.exception_handler(ApplicationError)
def handle_application_error(_request: Request, error: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.exception_handler(NaturalLanguageError)
def handle_natural_language_error(_request: Request, error: NaturalLanguageError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignUpCreate, session: DatabaseSession) -> AuthResponse:
    email = normalize_email(payload.email)
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    try:
        with _transaction(session):
            user = AppUser(display_name=payload.display_name)
            session.add(user)
            session.flush()
            session.add(
                PasswordCredential(
                    user_id=user.id,
                    email=email,
                    password_hash=password_hash.hash(payload.password),
                )
            )
            token, _record = create_session(session, user.id)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="An account already uses this email") from error
    return AuthResponse(access_token=token, user_id=user.id, display_name=user.display_name)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginCreate, session: DatabaseSession) -> AuthResponse:
    try:
        with _transaction(session):
            user_id = authenticate_password(session, payload.email, payload.password)
            user = session.get(AppUser, user_id)
            token, _record = create_session(session, user_id)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    assert user is not None
    return AuthResponse(access_token=token, user_id=user.id, display_name=user.display_name)


@app.get("/me")
def current_user(actor_user_id: ActorUserId, session: DatabaseSession) -> dict[str, object]:
    user = session.get(AppUser, actor_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    households = session.scalars(
        select(Household)
        .join(HouseholdMembership)
        .where(
            HouseholdMembership.user_id == actor_user_id,
            HouseholdMembership.status == "active",
        )
        .order_by(Household.name)
    ).all()
    return {
        "user_id": user.id,
        "display_name": user.display_name,
        "households": [
            {
                "id": household.id,
                "name": household.name,
                "default_timezone": household.default_timezone,
            }
            for household in households
        ],
    }


@app.post("/households", response_model=HouseholdResponse, status_code=status.HTTP_201_CREATED)
def create_household_route(
    payload: HouseholdCreate,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> HouseholdResponse:
    with _transaction(session):
        household = Household(
            name=payload.name,
            default_timezone=payload.default_timezone,
            created_by_user_id=actor_user_id,
        )
        household.memberships.append(
            HouseholdMembership(user_id=actor_user_id, role="administrator")
        )
        session.add(household)
        session.flush()
    return HouseholdResponse.model_validate(household, from_attributes=True)


@app.post("/households/{household_id}/invites", response_model=InviteResponse)
def create_household_invite(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> InviteResponse:
    membership = session.get(HouseholdMembership, (household_id, actor_user_id))
    if membership is None or membership.status != "active":
        raise HTTPException(status_code=404, detail="Household not found")
    code = secrets.token_urlsafe(24)
    with _transaction(session):
        invite = HouseholdInvite(
            household_id=household_id,
            created_by_user_id=actor_user_id,
            code_hash=digest_secret(code),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(invite)
        session.flush()
    return InviteResponse(invite_code=code, expires_at=invite.expires_at)


@app.post("/households/join", response_model=HouseholdResponse)
def join_household(
    payload: InviteAccept,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> HouseholdResponse:
    invite = session.scalar(
        select(HouseholdInvite).where(
            HouseholdInvite.code_hash == digest_secret(payload.invite_code)
        )
    )
    if invite is None or invite.used_at is not None or invite.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    with _transaction(session):
        existing = session.get(HouseholdMembership, (invite.household_id, actor_user_id))
        if existing is None:
            session.add(
                HouseholdMembership(household_id=invite.household_id, user_id=actor_user_id)
            )
        elif existing.status != "active":
            existing.status = "active"
            existing.left_at = None
        invite.used_by_user_id = actor_user_id
        invite.used_at = datetime.now(UTC)
        household = session.get(Household, invite.household_id)
    assert household is not None
    return HouseholdResponse.model_validate(household, from_attributes=True)


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get(
    "/households/{household_id}/members",
    response_model=list[HouseholdMemberResponse],
)
def list_household_members_route(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> list[HouseholdMemberResponse]:
    with _transaction(session):
        members = list_household_members(
            session, household_id=household_id, actor_user_id=actor_user_id
        )
    return [HouseholdMemberResponse(**member.__dict__) for member in members]


@app.get(
    "/households/{household_id}/calendar-items",
    response_model=list[CalendarItemResponse],
)
def list_calendar_items_route(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
    range_start: Annotated[datetime, Query()],
    range_end: Annotated[datetime, Query()],
) -> list[CalendarItemResponse]:
    with _transaction(session):
        items = list_calendar_items(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            starts_before=range_end,
            ends_after=range_start,
        )
        response_items = [_calendar_item_response(item) for item in items]
    return response_items


@app.get(
    "/households/{household_id}/work-items",
    response_model=list[WorkItemResponse],
)
def list_work_items_route(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> list[WorkItemResponse]:
    with _transaction(session):
        items = list_work_items(session, household_id=household_id, actor_user_id=actor_user_id)
    return [WorkItemResponse(**item.__dict__) for item in items]


@app.get(
    "/households/{household_id}/tasks",
    response_model=list[TaskSummary],
)
def list_tasks_route(
    household_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
    lifecycle_status: Annotated[Literal["active", "completed", "cancelled"] | None, Query()] = None,
    schedule_status: Annotated[Literal["scheduled", "unscheduled"] | None, Query()] = None,
    participant_user_id: Annotated[UUID | None, Query()] = None,
) -> list[TaskSummary]:
    with _transaction(session):
        results = list_tasks(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            lifecycle_status=lifecycle_status,
            schedule_status=schedule_status,
            participant_user_id=participant_user_id,
        )
    return [_task_summary(result) for result in results]


@app.get(
    "/households/{household_id}/tasks/{task_id}",
    response_model=TaskDetailResponse,
)
def get_task_route(
    household_id: UUID,
    task_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> TaskDetailResponse:
    with _transaction(session):
        result = _task_detail(
            get_task_details(
                session,
                household_id=household_id,
                actor_user_id=actor_user_id,
                task_id=task_id,
            )
        )
    return result


@app.patch(
    "/households/{household_id}/tasks/{task_id}",
    response_model=TaskDetailResponse,
)
def update_task_route(
    household_id: UUID,
    task_id: UUID,
    payload: TaskUpdate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> TaskDetailResponse:
    with _transaction(session):
        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation=f"update_task:{task_id}",
            payload=payload,
            response_model=TaskDetailResponse,
            response_status=200,
            action=lambda: _task_detail(
                update_task(
                    session,
                    household_id=household_id,
                    actor_user_id=actor_user_id,
                    task_id=task_id,
                    changes=payload.model_dump(exclude_unset=True),
                )
            ),
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.delete(
    "/households/{household_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task_route(
    household_id: UUID,
    task_id: UUID,
    actor_user_id: ActorUserId,
    session: DatabaseSession,
) -> Response:
    with _transaction(session):
        delete_task(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            task_id=task_id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/households/{household_id}/tasks/{task_id}/time-blocks",
    response_model=TaskTimeBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def schedule_task_route(
    household_id: UUID,
    task_id: UUID,
    payload: TaskScheduleCreate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> TaskTimeBlockResponse:
    with _transaction(session):
        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation=f"schedule_task:{task_id}",
            payload=payload,
            response_model=TaskTimeBlockResponse,
            action=lambda: _time_block_response(
                schedule_task(
                    session,
                    household_id=household_id,
                    actor_user_id=actor_user_id,
                    task_id=task_id,
                    **payload.model_dump(),
                )
            ),
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.patch(
    "/households/{household_id}/time-blocks/{time_block_id}",
    response_model=TaskTimeBlockResponse,
)
def update_time_block_route(
    household_id: UUID,
    time_block_id: UUID,
    payload: TimeBlockUpdate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> TaskTimeBlockResponse:
    with _transaction(session):
        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation=f"update_time_block:{time_block_id}",
            payload=payload,
            response_model=TaskTimeBlockResponse,
            response_status=200,
            action=lambda: _time_block_response(
                update_planned_time_block(
                    session,
                    household_id=household_id,
                    actor_user_id=actor_user_id,
                    time_block_id=time_block_id,
                    changes=payload.model_dump(exclude_unset=True),
                )
            ),
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


@app.patch(
    "/households/{household_id}/tasks/{task_id}/lifecycle",
    response_model=TaskDetailResponse,
)
def update_task_lifecycle_route(
    household_id: UUID,
    task_id: UUID,
    payload: TaskLifecycleUpdate,
    actor_user_id: ActorUserId,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    response: Response,
) -> TaskDetailResponse:
    with _transaction(session):
        result, replayed = execute_idempotent(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            operation=f"update_task_lifecycle:{task_id}",
            payload=payload,
            response_model=TaskDetailResponse,
            response_status=200,
            action=lambda: _task_detail(
                update_task_lifecycle(
                    session,
                    household_id=household_id,
                    actor_user_id=actor_user_id,
                    task_id=task_id,
                    lifecycle_status=payload.lifecycle_status,
                )
            ),
        )
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    return result


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
    with _transaction(session):
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
                    time_block_id=(result.time_block.id if result.time_block is not None else None),
                    task_id=result.completion.task_id,
                    participant_user_ids=result.participant_user_ids,
                    effective_duration_minutes=result.effective_duration_minutes,
                    work_scope=result.completion.work_scope,
                    counts_toward_fairness=result.completion.counts_toward_fairness,
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
                participant_user_ids=([actor_user_id] if command.started_at is not None else []),
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
                work_scope=result.task.work_scope,
                lifecycle_status=result.task.lifecycle_status,
                parent_task_id=result.task.parent_task_id,
                participant_user_ids=result.participant_user_ids,
                time_block_id=(result.time_block.id if result.time_block is not None else None),
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
    with _transaction(session):

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
                work_scope=created.task.work_scope,
                lifecycle_status=created.task.lifecycle_status,
                parent_task_id=created.task.parent_task_id,
                participant_user_ids=created.participant_user_ids,
                time_block_id=(created.time_block.id if created.time_block is not None else None),
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
    with _transaction(session):

        def perform_action() -> CompletedWorkResponse:
            recorded = record_completed_work(
                session,
                household_id=household_id,
                actor_user_id=actor_user_id,
                **payload.model_dump(),
            )
            return CompletedWorkResponse(
                completion_record_id=recorded.completion.id,
                time_block_id=(recorded.time_block.id if recorded.time_block is not None else None),
                task_id=recorded.completion.task_id,
                participant_user_ids=recorded.participant_user_ids,
                effective_duration_minutes=recorded.effective_duration_minutes,
                work_scope=recorded.completion.work_scope,
                counts_toward_fairness=recorded.completion.counts_toward_fairness,
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
    with _transaction(session):
        contributions = list_contributions(
            session,
            household_id=household_id,
            actor_user_id=actor_user_id,
            start_date=start_date,
            end_date=end_date,
        )
    return [ContributionResponse(**contribution.__dict__) for contribution in contributions]

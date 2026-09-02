from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class TaskCreate(ApiModel):
    title: str = Field(min_length=1)
    description: str | None = None
    category: str = Field(default="other", min_length=1)
    participant_user_ids: list[UUID] = Field(default_factory=list)
    parent_task_id: UUID | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "TaskCreate":
        if (self.scheduled_start is None) != (self.scheduled_end is None):
            raise ValueError("scheduled_start and scheduled_end must be provided together")
        if (
            self.scheduled_start is not None
            and self.scheduled_end is not None
            and self.scheduled_end <= self.scheduled_start
        ):
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class TaskResponse(ApiModel):
    id: UUID
    household_id: UUID
    title: str
    description: str | None
    category: str
    lifecycle_status: str
    parent_task_id: UUID | None
    participant_user_ids: list[UUID]
    time_block_id: UUID | None


class TaskSummary(ApiModel):
    id: UUID
    title: str
    category: str
    lifecycle_status: str
    parent_task_id: UUID | None
    participant_user_ids: list[UUID]
    scheduled: bool


class TaskTimeBlockResponse(ApiModel):
    id: UUID
    title: str | None
    starts_at: datetime
    ends_at: datetime
    status: str
    participant_user_ids: list[UUID]


class TaskDetailResponse(TaskSummary):
    household_id: UUID
    created_by_user_id: UUID
    description: str | None
    subtasks: list[TaskSummary]
    time_blocks: list[TaskTimeBlockResponse]


class TaskUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1)
    participant_user_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def validate_non_null_fields(self) -> "TaskUpdate":
        provided = self.model_fields_set
        if "title" in provided and self.title is None:
            raise ValueError("title cannot be null")
        if "category" in provided and self.category is None:
            raise ValueError("category cannot be null")
        if not provided:
            raise ValueError("at least one Task field must be provided")
        return self


class TaskScheduleCreate(ApiModel):
    starts_at: datetime
    ends_at: datetime
    participant_user_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "TaskScheduleCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class TimeBlockUpdate(ApiModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(planned|cancelled)$")

    @model_validator(mode="after")
    def validate_changes(self) -> "TimeBlockUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one Time Block field must be provided")
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValueError("ends_at must be after starts_at")
        return self


class TaskLifecycleUpdate(ApiModel):
    lifecycle_status: str = Field(pattern="^(active|completed|cancelled)$")


class CompletedWorkCreate(ApiModel):
    category: str = Field(default="other", min_length=1)
    description: str | None = None
    participant_user_ids: list[UUID] = Field(min_length=1)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_override_minutes: int | None = Field(default=None, gt=0)
    task_id: UUID | None = None
    complete_task: bool = False

    @model_validator(mode="after")
    def validate_duration(self) -> "CompletedWorkCreate":
        if (self.started_at is None) != (self.ended_at is None):
            raise ValueError("started_at and ended_at must be provided together")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at <= self.started_at
        ):
            raise ValueError("ended_at must be after started_at")
        if self.started_at is None and self.duration_override_minutes is None:
            raise ValueError("completed work requires a time range or duration override")
        if self.complete_task and self.task_id is None:
            raise ValueError("complete_task requires task_id")
        return self


class CompletedWorkResponse(ApiModel):
    completion_record_id: UUID
    time_block_id: UUID | None
    task_id: UUID | None
    participant_user_ids: list[UUID]
    effective_duration_minutes: int


class ContributionResponse(ApiModel):
    user_id: UUID
    contribution_day: date
    duration_minutes: int


class NaturalLanguageCreate(ApiModel):
    text: str = Field(min_length=1)
    reference_date: date
    parent_task_id: UUID | None = None


class NaturalLanguageResponse(ApiModel):
    interpreted_action: str
    task: TaskResponse | None = None
    completed_work: CompletedWorkResponse | None = None

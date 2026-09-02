from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


class AppUser(TimestampMixin, Base):
    __tablename__ = "app_users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(Text)

    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0", name="app_users_display_name_present"),
    )


class AuthIdentity(Base):
    __tablename__ = "auth_identities"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text)
    provider_subject: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    user: Mapped[AppUser] = relationship(back_populates="identities")

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="auth_identity_provider_subject_key"),
        CheckConstraint("length(trim(provider)) > 0", name="auth_identity_provider_present"),
        CheckConstraint("length(trim(provider_subject)) > 0", name="auth_identity_subject_present"),
    )


class PasswordCredential(TimestampMixin, Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="password_credentials_email_lowercase"),
        CheckConstraint("length(trim(email)) > 3", name="password_credentials_email_present"),
        CheckConstraint(
            "length(password_hash) > 20", name="password_credentials_password_hash_present"
        ),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (Index("auth_sessions_user_id_idx", "user_id"),)


class Household(TimestampMixin, Base):
    __tablename__ = "households"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"))
    default_timezone: Mapped[str] = mapped_column(Text, default="UTC", server_default="UTC")

    memberships: Mapped[list[HouseholdMembership]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="households_name_present"),
        CheckConstraint("length(trim(default_timezone)) > 0", name="households_timezone_present"),
    )


class HouseholdMembership(Base):
    __tablename__ = "household_memberships"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, default="member", server_default="member")
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    household: Mapped[Household] = relationship(back_populates="memberships")
    user: Mapped[AppUser] = relationship()

    __table_args__ = (
        CheckConstraint("role IN ('member', 'administrator')", name="membership_role_valid"),
        CheckConstraint("status IN ('active', 'inactive')", name="membership_status_valid"),
        CheckConstraint(
            "(status = 'active' AND left_at IS NULL) OR "
            "(status = 'inactive' AND left_at IS NOT NULL)",
            name="membership_status_matches_left_at",
        ),
    )


class HouseholdInvite(Base):
    __tablename__ = "household_invites"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "created_by_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="household_invites_creator_membership_fkey",
        ),
        CheckConstraint(
            "(used_at IS NULL AND used_by_user_id IS NULL) OR "
            "(used_at IS NOT NULL AND used_by_user_id IS NOT NULL)",
            name="household_invites_usage_matches",
        ),
        Index("household_invites_household_id_idx", "household_id"),
    )


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(nullable=False)
    parent_task_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, default="other", server_default="other")
    work_scope: Mapped[str] = mapped_column(Text, default="household", server_default="household")
    lifecycle_status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list[TaskParticipant]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    parent: Mapped[Task | None] = relationship(
        remote_side="Task.id", foreign_keys=[parent_task_id], back_populates="subtasks"
    )
    subtasks: Mapped[list[Task]] = relationship(
        foreign_keys=[parent_task_id], back_populates="parent"
    )

    __table_args__ = (
        UniqueConstraint("household_id", "id", name="tasks_household_id_id_key"),
        ForeignKeyConstraint(
            ["household_id", "created_by_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="tasks_creator_membership_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "parent_task_id"],
            ["tasks.household_id", "tasks.id"],
            name="tasks_parent_task_fkey",
        ),
        CheckConstraint("length(trim(title)) > 0", name="tasks_title_present"),
        CheckConstraint("length(trim(category)) > 0", name="tasks_category_present"),
        CheckConstraint("work_scope IN ('household', 'personal')", name="tasks_work_scope_valid"),
        CheckConstraint(
            "lifecycle_status IN ('active', 'completed', 'cancelled')",
            name="tasks_lifecycle_status_valid",
        ),
        CheckConstraint(
            "estimated_duration_minutes IS NULL OR estimated_duration_minutes > 0",
            name="tasks_estimated_duration_positive",
        ),
        CheckConstraint(
            "(lifecycle_status = 'active' AND completed_at IS NULL AND cancelled_at IS NULL) OR "
            "(lifecycle_status = 'completed' AND completed_at IS NOT NULL "
            "AND cancelled_at IS NULL) OR "
            "(lifecycle_status = 'cancelled' AND completed_at IS NULL "
            "AND cancelled_at IS NOT NULL)",
            name="tasks_lifecycle_timestamps_match",
        ),
        Index("tasks_household_status_idx", "household_id", "lifecycle_status"),
        Index(
            "tasks_parent_task_idx",
            "household_id",
            "parent_task_id",
            postgresql_where=text("parent_task_id IS NOT NULL"),
        ),
    )


class TaskParticipant(Base):
    __tablename__ = "task_participants"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    task: Mapped[Task] = relationship(back_populates="participants")
    user: Mapped[AppUser] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "task_id"],
            ["tasks.household_id", "tasks.id"],
            ondelete="CASCADE",
            name="task_participants_task_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="task_participants_membership_fkey",
        ),
        Index("task_participants_household_user_idx", "household_id", "user_id"),
    )


class RecurrenceRule(TimestampMixin, Base):
    __tablename__ = "recurrence_rules"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    frequency: Mapped[str] = mapped_column(Text)
    frequency_interval: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    days_of_week: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("task_id", name="recurrence_rules_task_id_key"),
        UniqueConstraint("household_id", "id", name="recurrence_rules_household_id_id_key"),
        UniqueConstraint("task_id", "id", name="recurrence_rules_task_id_id_key"),
        ForeignKeyConstraint(
            ["household_id", "task_id"],
            ["tasks.household_id", "tasks.id"],
            ondelete="CASCADE",
            name="recurrence_rules_task_fkey",
        ),
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'yearly')",
            name="recurrence_rules_frequency_valid",
        ),
        CheckConstraint("frequency_interval > 0", name="recurrence_rules_interval_positive"),
        CheckConstraint(
            "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31",
            name="recurrence_rules_day_of_month_valid",
        ),
        CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name="recurrence_rules_dates_valid"
        ),
        CheckConstraint(
            "days_of_week IS NULL OR days_of_week <@ ARRAY[0,1,2,3,4,5,6]::smallint[]",
            name="recurrence_rules_weekdays_valid",
        ),
    )


class TaskInstance(TimestampMixin, Base):
    __tablename__ = "task_instances"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    recurrence_rule_id: Mapped[UUID | None] = mapped_column(Uuid)
    occurrence_date: Mapped[date] = mapped_column(Date)
    lifecycle_status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list[TaskInstanceParticipant]] = relationship(
        back_populates="task_instance", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("task_id", "occurrence_date", name="task_instances_task_date_key"),
        UniqueConstraint("household_id", "id", name="task_instances_household_id_id_key"),
        UniqueConstraint("task_id", "id", name="task_instances_task_id_id_key"),
        ForeignKeyConstraint(
            ["household_id", "task_id"],
            ["tasks.household_id", "tasks.id"],
            ondelete="CASCADE",
            name="task_instances_task_fkey",
        ),
        ForeignKeyConstraint(
            ["task_id", "recurrence_rule_id"],
            ["recurrence_rules.task_id", "recurrence_rules.id"],
            name="task_instances_recurrence_rule_fkey",
        ),
        CheckConstraint(
            "lifecycle_status IN ('active', 'completed', 'skipped', 'cancelled')",
            name="task_instances_lifecycle_status_valid",
        ),
        CheckConstraint(
            "(lifecycle_status = 'completed' AND completed_at IS NOT NULL) OR "
            "(lifecycle_status <> 'completed' AND completed_at IS NULL)",
            name="task_instances_completion_timestamp_matches",
        ),
        Index("task_instances_household_date_idx", "household_id", "occurrence_date"),
    )


class TaskInstanceParticipant(Base):
    __tablename__ = "task_instance_participants"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    task_instance_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    task_instance: Mapped[TaskInstance] = relationship(back_populates="participants")
    user: Mapped[AppUser] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "task_instance_id"],
            ["task_instances.household_id", "task_instances.id"],
            ondelete="CASCADE",
            name="task_instance_participants_instance_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="task_instance_participants_membership_fkey",
        ),
        Index("task_instance_participants_household_user_idx", "household_id", "user_id"),
    )


class TimeBlock(TimestampMixin, Base):
    __tablename__ = "time_blocks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    block_kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    work_scope: Mapped[str] = mapped_column(Text, default="household", server_default="household")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list[TimeBlockParticipant]] = relationship(
        back_populates="time_block", cascade="all, delete-orphan"
    )
    task_links: Mapped[list[TimeBlockTask]] = relationship(
        back_populates="time_block", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("household_id", "id", name="time_blocks_household_id_id_key"),
        ForeignKeyConstraint(
            ["household_id", "created_by_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="time_blocks_creator_membership_fkey",
        ),
        CheckConstraint("block_kind IN ('planned', 'actual')", name="time_blocks_kind_valid"),
        CheckConstraint(
            "work_scope IN ('household', 'personal')", name="time_blocks_work_scope_valid"
        ),
        CheckConstraint(
            "status IN ('planned', 'completed', 'cancelled')", name="time_blocks_status_valid"
        ),
        CheckConstraint("ends_at > starts_at", name="time_blocks_time_range_valid"),
        CheckConstraint(
            "(block_kind = 'planned' AND status IN ('planned', 'completed', 'cancelled')) OR "
            "(block_kind = 'actual' AND status = 'completed')",
            name="time_blocks_kind_matches_status",
        ),
        Index("time_blocks_household_starts_at_idx", "household_id", "starts_at"),
    )


class TimeBlockParticipant(Base):
    __tablename__ = "time_block_participants"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    time_block_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    time_block: Mapped[TimeBlock] = relationship(back_populates="participants")
    user: Mapped[AppUser] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "time_block_id"],
            ["time_blocks.household_id", "time_blocks.id"],
            ondelete="CASCADE",
            name="time_block_participants_block_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="time_block_participants_membership_fkey",
        ),
        Index("time_block_participants_household_user_idx", "household_id", "user_id"),
    )


class TimeBlockTask(Base):
    __tablename__ = "time_block_tasks"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    time_block_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_instance_id: Mapped[UUID | None] = mapped_column(Uuid)
    planned_minutes: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    time_block: Mapped[TimeBlock] = relationship(back_populates="task_links")
    task: Mapped[Task] = relationship(overlaps="task_links,time_block")
    task_instance: Mapped[TaskInstance | None] = relationship(overlaps="task")

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "time_block_id"],
            ["time_blocks.household_id", "time_blocks.id"],
            ondelete="CASCADE",
            name="time_block_tasks_block_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "task_id"],
            ["tasks.household_id", "tasks.id"],
            ondelete="CASCADE",
            name="time_block_tasks_task_fkey",
        ),
        ForeignKeyConstraint(
            ["task_id", "task_instance_id"],
            ["task_instances.task_id", "task_instances.id"],
            name="time_block_tasks_instance_fkey",
        ),
        CheckConstraint(
            "planned_minutes IS NULL OR planned_minutes > 0",
            name="time_block_tasks_planned_minutes_positive",
        ),
        CheckConstraint("sort_order >= 0", name="time_block_tasks_sort_order_valid"),
    )


class CompletionRecord(TimestampMixin, Base):
    __tablename__ = "completion_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(Uuid)
    task_instance_id: Mapped[UUID | None] = mapped_column(Uuid)
    time_block_id: Mapped[UUID | None] = mapped_column(Uuid)
    category: Mapped[str] = mapped_column(Text, default="other", server_default="other")
    work_scope: Mapped[str] = mapped_column(Text, default="household", server_default="household")
    counts_toward_fairness: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    description: Mapped[str | None] = mapped_column(Text)
    duration_override_minutes: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list[CompletionRecordParticipant]] = relationship(
        back_populates="completion_record", cascade="all, delete-orphan"
    )
    task: Mapped[Task | None] = relationship()
    task_instance: Mapped[TaskInstance | None] = relationship(overlaps="task")
    time_block: Mapped[TimeBlock | None] = relationship(overlaps="task")

    @property
    def effective_duration_minutes(self) -> int:
        if self.duration_override_minutes is not None:
            return self.duration_override_minutes
        if self.started_at is not None and self.ended_at is not None:
            seconds = (self.ended_at - self.started_at).total_seconds()
            return int((seconds + 59) // 60)
        if self.time_block is not None:
            seconds = (self.time_block.ends_at - self.time_block.starts_at).total_seconds()
            return int((seconds + 59) // 60)
        raise ValueError("A Completion Record requires a duration source")

    __table_args__ = (
        UniqueConstraint("household_id", "id", name="completion_records_household_id_id_key"),
        ForeignKeyConstraint(
            ["household_id", "created_by_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="completion_records_creator_membership_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "task_id"],
            ["tasks.household_id", "tasks.id"],
            name="completion_records_task_fkey",
        ),
        ForeignKeyConstraint(
            ["task_id", "task_instance_id"],
            ["task_instances.task_id", "task_instances.id"],
            name="completion_records_instance_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "time_block_id"],
            ["time_blocks.household_id", "time_blocks.id"],
            name="completion_records_time_block_fkey",
        ),
        CheckConstraint("length(trim(category)) > 0", name="completion_records_category_present"),
        CheckConstraint(
            "work_scope IN ('household', 'personal')",
            name="completion_records_work_scope_valid",
        ),
        CheckConstraint(
            "duration_override_minutes IS NULL OR duration_override_minutes > 0",
            name="completion_records_override_positive",
        ),
        CheckConstraint(
            "(started_at IS NULL AND ended_at IS NULL) OR "
            "(started_at IS NOT NULL AND ended_at IS NOT NULL AND ended_at > started_at)",
            name="completion_records_time_range_valid",
        ),
        CheckConstraint(
            "duration_override_minutes IS NOT NULL OR "
            "(started_at IS NOT NULL AND ended_at IS NOT NULL) OR time_block_id IS NOT NULL",
            name="completion_records_duration_source_present",
        ),
        CheckConstraint(
            "task_instance_id IS NULL OR task_id IS NOT NULL",
            name="completion_records_instance_requires_task",
        ),
        Index("completion_records_household_completed_at_idx", "household_id", "completed_at"),
    )


class CompletionRecordParticipant(Base):
    __tablename__ = "completion_record_participants"

    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    completion_record_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    completion_record: Mapped[CompletionRecord] = relationship(back_populates="participants")
    user: Mapped[AppUser] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "completion_record_id"],
            ["completion_records.household_id", "completion_records.id"],
            ondelete="CASCADE",
            name="completion_participants_record_fkey",
        ),
        ForeignKeyConstraint(
            ["household_id", "user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="completion_participants_membership_fkey",
        ),
        Index("completion_participants_household_user_idx", "household_id", "user_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "actor_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="audit_events_actor_membership_fkey",
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'delete')", name="audit_events_action_valid"
        ),
        CheckConstraint("length(trim(entity_type)) > 0", name="audit_events_entity_type_present"),
        CheckConstraint(
            "before_values IS NOT NULL OR after_values IS NOT NULL",
            name="audit_events_values_present",
        ),
        Index("audit_events_household_occurred_at_idx", "household_id", text("occurred_at DESC")),
    )


class IntegrationRequest(Base):
    __tablename__ = "integration_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    client_name: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["household_id", "actor_user_id"],
            ["household_memberships.household_id", "household_memberships.user_id"],
            name="integration_requests_actor_membership_fkey",
        ),
        UniqueConstraint(
            "actor_user_id",
            "client_name",
            "idempotency_key",
            name="integration_requests_idempotency_key",
        ),
        CheckConstraint("length(trim(client_name)) > 0", name="integration_client_name_present"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="integration_key_present"),
        CheckConstraint("length(trim(operation)) > 0", name="integration_operation_present"),
        CheckConstraint("length(request_hash) = 64", name="integration_request_hash_valid"),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="integration_response_status_valid",
        ),
    )

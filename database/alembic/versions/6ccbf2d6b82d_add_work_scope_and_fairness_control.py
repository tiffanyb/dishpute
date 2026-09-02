"""Add work scope and fairness control.

Revision ID: 6ccbf2d6b82d
Revises: 672bb3524cc6
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ccbf2d6b82d"
down_revision: str | Sequence[str] | None = "672bb3524cc6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("work_scope", sa.Text(), server_default="household", nullable=False),
    )
    op.create_check_constraint(
        "tasks_work_scope_valid",
        "tasks",
        "work_scope IN ('household', 'personal')",
    )
    op.add_column(
        "time_blocks",
        sa.Column("work_scope", sa.Text(), server_default="household", nullable=False),
    )
    op.create_check_constraint(
        "time_blocks_work_scope_valid",
        "time_blocks",
        "work_scope IN ('household', 'personal')",
    )
    op.add_column(
        "completion_records",
        sa.Column("work_scope", sa.Text(), server_default="household", nullable=False),
    )
    op.add_column(
        "completion_records",
        sa.Column(
            "counts_toward_fairness",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "completion_records_work_scope_valid",
        "completion_records",
        "work_scope IN ('household', 'personal')",
    )
    op.execute("DROP VIEW member_contribution_durations")
    op.execute(
        """
        CREATE VIEW member_contribution_durations AS
        SELECT
            completion.household_id,
            participant.user_id,
            date_trunc(
                'day',
                completion.completed_at AT TIME ZONE household.default_timezone
            )::date AS contribution_day,
            sum(duration.duration_minutes)::bigint AS duration_minutes
        FROM completion_records AS completion
        JOIN completion_record_participants AS participant
            ON participant.completion_record_id = completion.id
        JOIN completion_record_durations AS duration
            ON duration.completion_record_id = completion.id
        JOIN households AS household
            ON household.id = completion.household_id
        WHERE completion.counts_toward_fairness
        GROUP BY
            completion.household_id,
            participant.user_id,
            date_trunc(
                'day',
                completion.completed_at AT TIME ZONE household.default_timezone
            )::date
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW member_contribution_durations")
    op.execute(
        """
        CREATE VIEW member_contribution_durations AS
        SELECT
            completion.household_id,
            participant.user_id,
            date_trunc(
                'day',
                completion.completed_at AT TIME ZONE household.default_timezone
            )::date AS contribution_day,
            sum(duration.duration_minutes)::bigint AS duration_minutes
        FROM completion_records AS completion
        JOIN completion_record_participants AS participant
            ON participant.completion_record_id = completion.id
        JOIN completion_record_durations AS duration
            ON duration.completion_record_id = completion.id
        JOIN households AS household
            ON household.id = completion.household_id
        GROUP BY
            completion.household_id,
            participant.user_id,
            date_trunc(
                'day',
                completion.completed_at AT TIME ZONE household.default_timezone
            )::date
        """
    )
    op.drop_constraint("completion_records_work_scope_valid", "completion_records", type_="check")
    op.drop_column("completion_records", "counts_toward_fairness")
    op.drop_column("completion_records", "work_scope")
    op.drop_constraint("time_blocks_work_scope_valid", "time_blocks", type_="check")
    op.drop_column("time_blocks", "work_scope")
    op.drop_constraint("tasks_work_scope_valid", "tasks", type_="check")
    op.drop_column("tasks", "work_scope")

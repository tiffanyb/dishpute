"""Add request hash for idempotency.

Revision ID: 672bb3524cc6
Revises: fb99f249208d
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "672bb3524cc6"
down_revision: str | Sequence[str] | None = "fb99f249208d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integration_requests",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE integration_requests "
        "SET request_hash = repeat('0', 64) WHERE request_hash IS NULL"
    )
    op.alter_column("integration_requests", "request_hash", nullable=False)
    op.create_check_constraint(
        "integration_request_hash_valid",
        "integration_requests",
        "length(request_hash) = 64",
    )


def downgrade() -> None:
    op.drop_constraint(
        "integration_request_hash_valid", "integration_requests", type_="check"
    )
    op.drop_column("integration_requests", "request_hash")

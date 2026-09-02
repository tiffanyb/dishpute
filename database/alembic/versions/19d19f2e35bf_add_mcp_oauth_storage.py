"""add mcp oauth storage

Revision ID: 19d19f2e35bf
Revises: b9efacee55d1
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "19d19f2e35bf"
down_revision: str | None = "b9efacee55d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("client_secret", sa.Text()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "oauth_authorization_requests",
        sa.Column("request_token_hash", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "oauth_access_grants",
        sa.Column("token_hash", sa.String(64), sa.ForeignKey("auth_sessions.token_hash", ondelete="CASCADE"), primary_key=True),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
    )
    op.create_table(
        "oauth_refresh_grants",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.Uuid(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_refresh_grants")
    op.drop_table("oauth_access_grants")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_authorization_requests")
    op.drop_table("oauth_clients")

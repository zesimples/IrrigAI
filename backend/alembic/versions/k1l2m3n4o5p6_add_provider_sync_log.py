"""Add provider_sync_log table

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-04
"""

import sqlalchemy as sa
from alembic import op

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_sync_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("farm_id", sa.dialects.postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("farm.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_msg", sa.Text, nullable=True),
        sa.Column("last_latency_ms", sa.Integer, nullable=True),
        sa.Column("last_records_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_provider_sync_log_farm_id", "provider_sync_log", ["farm_id"])
    op.create_unique_constraint(
        "uq_provider_sync_log_farm_provider", "provider_sync_log", ["farm_id", "provider"]
    )


def downgrade() -> None:
    op.drop_table("provider_sync_log")
